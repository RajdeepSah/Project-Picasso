"""Allowlisted main.nc publication with backup, identity checks and readback."""

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import stat
import sys
import threading
import uuid

from ..drawing.errors import DrawingError
from ..models import AutoSyncState, ExportRequest, StorageStatus, StorageTarget, TargetsResponse, TransferRecord
from .repository import atomic_write, directory, now, read_regular, sha
from .targets import LinuxTargets, instance, main_hash, test_target


class ExportManager:
    def __init__(self, repository, jobs, mirror: Path, provider=None):
        self.repository, self.jobs, self.mirror = repository, jobs, mirror.absolute()
        self.provider = provider or LinuxTargets()
        self.operation = threading.Lock()

    def candidates(self):
        targets, error = self.provider.discover()
        test = self.repository.root / 'test-card'
        if self.repository.setting('test_target_enabled', False) and test.is_dir() and not test.is_symlink():
            try:
                targets.append(test_target(test))
            except (OSError, DrawingError):
                pass
        return targets, error

    def targets(self):
        targets, error = self.candidates()
        selected = self.repository.setting('selected_target')
        previous = self.repository.setting('selected_target_snapshot')
        if previous and not any(item.id == selected for item in targets):
            previous.update(available=False, writable=False, reason='Selected target is unmounted/unavailable.')
            targets.append(StorageTarget.model_validate(previous))
        try:
            mirror_hash = main_hash(self.mirror) if self.mirror.is_dir() and not self.mirror.is_symlink() else None
        except (OSError, DrawingError):
            mirror_hash = None
        return TargetsResponse(targets=targets, selected_target_id=selected,
                               discovery_supported=sys.platform == 'linux', discovery_error=error,
                               local_mirror_sha256=mirror_hash, auto_sync=self.auto_state())

    def find(self, identity):
        for target in self.candidates()[0]:
            if target.id == identity and target.available:
                if not target.writable:
                    raise DrawingError('TARGET_READ_ONLY', target.reason, 409)
                return target
        raise DrawingError('TARGET_UNAVAILABLE', 'The selected card/test directory is unavailable. Reinsert the same volume or explicitly select another target.', 409)

    def create_test(self):
        path = directory(self.repository.root / 'test-card')
        self.repository.set_setting('test_target_enabled', True)
        target = test_target(path)
        self.select(target.id)
        return target

    def select(self, identity):
        with self.exclusive():
            return self._select(identity)

    def _select(self, identity):
        target = self.find(identity)
        self.repository.set_setting('selected_target', identity)
        self.repository.set_setting('selected_target_snapshot', target.model_dump())
        self.repository.set_setting('auto_sync', AutoSyncState().model_dump())

    def status(self):
        selected = self.repository.setting('selected_target')
        targets, error = self.candidates()
        target = next((item for item in targets if item.id == selected), None)
        return StorageStatus(state=('test_directory' if target.kind == 'test_directory' else 'ready') if target else 'unmounted' if selected else 'not_configured',
                             discovery_performed=error is None, reason=target.reason if target else error or 'No selected mounted card is available. No card was written.')

    @contextmanager
    def exclusive(self):
        if not self.operation.acquire(False):
            raise DrawingError('TRANSFER_BUSY', 'Another export is in progress. Retry shortly.', 409)
        descriptor = None
        try:
            if os.name != 'posix':
                raise DrawingError('EXPORT_PLATFORM_UNSUPPORTED', 'Verified filesystem export currently requires the Linux/POSIX implementation.', 409)
            import fcntl
            descriptor = os.open(self.repository.root / 'export.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DrawingError('TRANSFER_BUSY', 'Another Picasso process owns the export lock.', 409) from exc
            with self.repository.lock:
                yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            self.operation.release()

    @staticmethod
    def read_at(root_fd, name, limit=16_000_000):
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise DrawingError('UNSAFE_TARGET_FILE', 'main.nc must be a regular file no larger than 16 MB.', 409)
            content = stream.read(limit + 1)
            if len(content) > limit:
                raise DrawingError('UNSAFE_TARGET_FILE', 'Target file exceeds the backup limit.', 409)
            return content

    def _write_at(self, root_fd, name, content, check):
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root_fd)
        with os.fdopen(descriptor, 'wb') as stream:
            for offset in range(0, len(content), 65536):
                check(); stream.write(content[offset:offset+65536])
            stream.flush(); os.fsync(stream.fileno())

    def _backup(self, content, target_id):
        folder = directory(self.repository.backups / sha(target_id.encode())[:24])
        path = folder / f'{uuid.uuid4().hex}-{sha(content)[:12]}.nc'
        atomic_write(path, content)
        if sha(read_regular(path)) != sha(content):
            raise DrawingError('BACKUP_MISMATCH', 'Original main.nc backup failed checksum verification.', 409)
        relative = path.relative_to(self.repository.root).as_posix()
        if target_id == 'local-mirror' and self.repository.setting('original_mirror_backup') is None:
            self.repository.set_setting('original_mirror_backup', relative)
        return relative

    def _publish(self, job, path, expected_hash, target_id, target_kind, confirm=None):
        if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_dir():
            raise DrawingError('UNSAFE_TARGET', 'Export requires an existing non-symlink directory.', 409)
        root_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        snapshot = os.fstat(root_fd)
        code = job.gcode.encode('ascii')
        temp = 'P' + uuid.uuid4().hex[:7] + '.TMP'
        meta_temp = 'P' + uuid.uuid4().hex[:7] + '.TMP'
        record = TransferRecord(id=uuid.uuid4().hex, job_id=job.id, target_id=target_id, target_kind=target_kind,
                                status='copying', gcode_sha256=job.gcode_sha256, previous_sha256=expected_hash,
                                backup=None, message='Copying managed main.nc.', created_at=now())
        def check():
            if any(part.is_symlink() for part in (path, *path.parents)):
                raise DrawingError('TARGET_CHANGED', 'Export root changed to a symlink.', 409)
            current = path.stat()
            if (current.st_dev, current.st_ino) != (snapshot.st_dev, snapshot.st_ino):
                raise DrawingError('TARGET_CHANGED', 'The mounted volume/root changed during export.', 409)
        try:
            self.repository.record_transfer(record)
            check()
            if confirm:
                confirm()
            filesystem = os.fstatvfs(root_fd)
            if filesystem.f_flag & getattr(os, 'ST_RDONLY', 1):
                raise DrawingError('TARGET_READ_ONLY', 'The filesystem is mounted read-only.', 409)
            if filesystem.f_bavail * filesystem.f_frsize < len(code) + 8192:
                raise DrawingError('TARGET_FULL', 'Not enough free space for a verified staged copy.', 409)
            previous = self.read_at(root_fd, 'main.nc')
            if (sha(previous) if previous is not None else None) != expected_hash:
                raise DrawingError('TARGET_CHANGED', 'main.nc changed externally. Review the new file and retry explicitly.', 409)
            if previous is not None:
                record.backup = self._backup(previous, target_id)
                self.repository.record_transfer(record)
            self._write_at(root_fd, temp, code, check)
            if sha(self.read_at(root_fd, temp)) != job.gcode_sha256:
                raise DrawingError('COPY_CHECKSUM_MISMATCH', 'Temporary copy checksum mismatch. main.nc was not activated.', 409)
            metadata = json.dumps({'schema_version': 1, 'job_id': job.id, 'revision_id': job.revision_id,
                                   'gcode_sha256': job.gcode_sha256, 'mode': job.mode, 'manual_origin_required': True}).encode()
            self._write_at(root_fd, meta_temp, metadata, check)
            # Do not replace a user-created metadata symlink/directory.
            self.read_at(root_fd, 'PICASSO.JSN')
            check()
            if confirm:
                confirm()
            self.jobs.validate_for_export(job.id)
            current = self.read_at(root_fd, 'main.nc')
            if (sha(current) if current is not None else None) != expected_hash:
                raise DrawingError('TARGET_CHANGED', 'main.nc changed during staging. No activation performed.', 409)
            os.replace(temp, 'main.nc', src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.replace(meta_temp, 'PICASSO.JSN', src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.fsync(root_fd)
            check()
            if confirm:
                confirm()
            actual = self.read_at(root_fd, 'main.nc')
            if actual is None or sha(actual) != job.gcode_sha256:
                raise DrawingError('COPY_CHECKSUM_MISMATCH', 'Final main.nc readback failed. Do not use the target; inspect and retry.', 409)
            record.status = 'verified'; record.bytes_verified = len(actual)
            record.message = ('Test-directory export verified. No physical card was written.' if target_kind == 'test_directory' else
                              'Local mirror staged and verified.' if target_kind == 'local_mirror' else
                              'Physical-card file readback verified. Safely eject, move the card to the machine, establish origin and use its SD menu; no drawing was started.')
            self.repository.record_transfer(record)
            return record
        except BaseException as exc:
            record.status = 'failed'; record.message = str(exc)
            self.repository.record_transfer(record)
            if isinstance(exc, DrawingError):
                raise
            if isinstance(exc, OSError):
                code_name = 'TARGET_FULL' if exc.errno == errno.ENOSPC else 'TARGET_IO_ERROR'
                raise DrawingError(code_name, f'Export failed: {exc.strerror or type(exc).__name__}. No verified success is recorded.', 409) from exc
            raise
        finally:
            for name in (temp, meta_temp):
                try:
                    os.unlink(name, dir_fd=root_fd)
                except OSError:
                    pass
            os.close(root_fd)

    def stage(self, identity, request):
        job = self.jobs.validate_for_export(identity)
        if job.mode != 'physical':
            raise DrawingError('SIMULATION_ONLY', 'Simulation jobs cannot update the physical SD mirror.', 409)
        if not request.acknowledge_replace:
            raise DrawingError('REPLACE_NOT_ACKNOWLEDGED', 'Acknowledge backup and replacement of local main.nc.', 409)
        with self.exclusive():
            return self._publish(job, self.mirror, request.expected_existing_sha256, 'local-mirror', 'local_mirror')

    def export(self, identity, request):
        with self.exclusive():
            return self._export(identity, request)

    def _export(self, identity, request):
        job = self.jobs.validate_for_export(identity)
        if request.expected_job_sha256 != job.gcode_sha256:
            raise DrawingError('STALE_JOB', 'Prepared job checksum differs. Reload the selected immutable job.', 409)
        if not request.acknowledge_replace:
            raise DrawingError('REPLACE_NOT_ACKNOWLEDGED', 'Acknowledge backing up and replacing the selected main.nc.', 409)
        target = self.find(request.target_id)
        if self.repository.setting('selected_target') != target.id:
            raise DrawingError('TARGET_NOT_SELECTED', 'Select this target explicitly before exporting.', 409)
        selected = self.repository.setting('selected_target_snapshot')
        if not selected or selected['volume_uuid'] != target.volume_uuid or selected['path'] != target.path:
            raise DrawingError('TARGET_CHANGED', 'The selected volume identity changed. Select it explicitly again.', 409)
        if target.kind == 'physical_card':
            if job.mode != 'physical' or not request.computer_owns_card or not request.manual_start_understood:
                raise DrawingError('PHYSICAL_EXPORT_NOT_READY', 'A physical job, exclusive computer ownership of the card, and acknowledgement of the manual origin/start procedure are required.', 409)
        elif request.stage_local_mirror:
            raise DrawingError('SIMULATION_ONLY', 'Test-directory exports cannot modify the local SD mirror.', 409)
        if target.current_main_sha256 != request.expected_existing_sha256:
            raise DrawingError('TARGET_CHANGED', 'main.nc changed since it was reviewed. Refresh and acknowledge its new contents.', 409)
        def confirm():
            fresh = self.find(target.id)
            if fresh.instance != target.instance or fresh.volume_uuid != target.volume_uuid or fresh.path != target.path:
                raise DrawingError('TARGET_CHANGED', 'The mounted card identity changed. Select the intended card again.', 409)
        mirror_updated = False
        if request.stage_local_mirror:
            # The explicit physical export also stages this same immutable job locally.
            self._publish(job, self.mirror, request.expected_local_mirror_sha256, 'local-mirror', 'local_mirror')
            mirror_updated = True
        result = self._publish(job, Path(target.path), request.expected_existing_sha256, target.id, target.kind, confirm)
        result.local_mirror_updated = mirror_updated
        self.repository.record_transfer(result)
        return result

    def auto_state(self):
        return AutoSyncState.model_validate(self.repository.setting('auto_sync', AutoSyncState().model_dump()))

    def arm(self, request):
        with self.exclusive():
            return self._arm(request)

    def _arm(self, request):
        if not request.enabled:
            self.repository.set_setting('auto_sync', AutoSyncState().model_dump())
            self.repository.set_setting('auto_sync_request', None)
            return self.auto_state()
        if not request.job_id or request.export is None or not request.export.acknowledge_replace:
            raise DrawingError('AUTO_SYNC_NOT_READY', 'Choose a prepared job, selected target and explicit replacement acknowledgements.')
        job = self.jobs.validate_for_export(request.job_id)
        try:
            target = self.find(request.export.target_id)
        except DrawingError as exc:
            previous = self.repository.setting('selected_target_snapshot')
            if exc.code != 'TARGET_UNAVAILABLE' or not previous or previous['id'] != request.export.target_id:
                raise
            target = StorageTarget.model_validate(previous)
        if target.id != self.repository.setting('selected_target') or request.export.expected_job_sha256 != job.gcode_sha256:
            raise DrawingError('AUTO_SYNC_NOT_READY', 'The selected target/job changed.', 409)
        if target.kind == 'physical_card' and (job.mode != 'physical' or not request.export.computer_owns_card or not request.export.manual_start_understood):
            raise DrawingError('PHYSICAL_EXPORT_NOT_READY', 'Physical export acknowledgements are required.', 409)
        if target.kind == 'test_directory' and request.export.stage_local_mirror:
            raise DrawingError('SIMULATION_ONLY', 'Test exports cannot update the physical SD mirror.', 409)
        state = AutoSyncState(enabled=True, job_id=job.id, target_id=target.id, status='armed', message='This frozen job will be copied when the approved target is accessible, including now. No drawing will start.')
        self.repository.set_setting('auto_sync_request', request.export.model_dump())
        self.repository.set_setting('auto_sync_last_instance', None)
        self.repository.set_setting('auto_sync', state.model_dump())
        return state

    def poll_auto_sync(self):
        if not self.auto_state().enabled:
            return
        try:
            with self.exclusive():
                self._poll_auto_sync()
        except DrawingError as exc:
            if exc.code != 'TRANSFER_BUSY':
                raise

    def _poll_auto_sync(self):
        state = self.auto_state()
        if not state.enabled:
            return
        try:
            self.jobs.validate_for_export(state.job_id)
            target = self.find(state.target_id)
            key = f'{target.instance}:{state.job_id}'
            request = ExportRequest.model_validate(self.repository.setting('auto_sync_request'))
            if target.current_main_sha256 != request.expected_existing_sha256:
                raise DrawingError('TARGET_CHANGED', 'main.nc was edited outside Picasso. Automatic export paused for review.', 409)
            if request.stage_local_mirror and main_hash(self.mirror) != request.expected_local_mirror_sha256:
                raise DrawingError('TARGET_CHANGED', 'The local SD mirror changed externally. Automatic export paused for review.', 409)
            if key == self.repository.setting('auto_sync_last_instance'):
                return
            record = self._export(state.job_id, request)
            state.status = 'verified'; state.message = record.message; state.last_transfer_id = record.id
            request.expected_existing_sha256 = record.gcode_sha256
            if request.stage_local_mirror:
                request.expected_local_mirror_sha256 = record.gcode_sha256
            self.repository.set_setting('auto_sync_request', request.model_dump())
            self.repository.set_setting('auto_sync_last_instance', key)
        except DrawingError as exc:
            if exc.code in ('TARGET_UNAVAILABLE', 'TRANSFER_BUSY'):
                state.status = 'waiting'; state.message = exc.message
                if exc.code == 'TARGET_UNAVAILABLE':
                    self.repository.set_setting('auto_sync_last_instance', None)
            else:
                state.enabled = False; state.status = 'paused_for_review'; state.message = exc.message
        except OSError as exc:
            state.enabled = False; state.status = 'paused_for_review'; state.message = f'Filesystem export interrupted: {type(exc).__name__}.'
        self.repository.set_setting('auto_sync', state.model_dump())
