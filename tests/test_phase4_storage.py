from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import sqlite3
from threading import Event
from types import SimpleNamespace
import uuid

import pytest

from backend.app.drawing.errors import DrawingError
from backend.app.drawing.service import DraftService
from backend.app.models import (AutoSyncRequest, CalibrationInput, CalibrationSaveRequest, ExportRequest,
                                GenerateRequest, PreparationRequest, StageRequest, StorageTarget)
from backend.app.profiles import load_reference_profiles
from backend.app.storage.exporter import ExportManager
from backend.app.storage.preparation import JobManager, ProfileManager
from backend.app.storage.repository import Repository, sha
from backend.app.storage.targets import instance

ROOT = Path(__file__).resolve().parents[1]


def calibration(**changes):
    value = dict(label='Test fixture measured profile', base_reference_id='reference-350', board='Test fixture UNO',
                 separation_mm=350, anchor_y_mm=250, spool_diameter_mm=35, steps_per_turn=2048,
                 pen_up_degrees=85, pen_down_degrees=70, allowed_region=dict(min_x_mm=-150,max_x_mm=150,min_y_mm=-100,max_y_mm=150,margin_mm=5),
                 rope_min_mm=100, rope_max_mm=600, measured_by='Automated test fixture', measurement_notes='Synthetic measurements, never real hardware evidence.',
                 origin_procedure='Synthetic test: reference physical and firmware origin before each run.',
                 firmware_matches_measurements=True, pen_lift_and_holding_tested=True, workspace_tested=True, verified=True)
    value.update(changes)
    return CalibrationInput(**value)


class FakeVolumes:
    def __init__(self, path):
        self.path, self.online, self.writable, self.generation = path, True, True, 1
    def discover(self):
        if not self.online:
            return [], None
        main = self.path/'main.nc'
        data = main.read_bytes() if main.exists() and not main.is_symlink() else None
        return [StorageTarget(id='fixture-card', label='FAKE CARD (test only)', path=str(self.path), kind='physical_card',
                              filesystem='vfat', volume_uuid='fixture-volume-uuid', instance=f'{instance(self.path)}:{self.generation}',
                              available=True, writable=self.writable, reason='Fake volume adapter, not a real card.',
                              current_main_sha256=sha(data) if data is not None else None)], None


@pytest.fixture
def system(tmp_path):
    repo = Repository(tmp_path/'data')
    drafts = DraftService(repository=repo)
    profiles = ProfileManager(repo, load_reference_profiles(ROOT))
    profile = profiles.save(CalibrationSaveRequest(calibration=calibration(), select_for_preparation=True))
    jobs = JobManager(repo, drafts, profiles)
    mirror = tmp_path/'mirror'; mirror.mkdir(); (mirror/'main.nc').write_bytes(b'ORIGINAL MIRROR\n')
    card = tmp_path/'fake-card'; card.mkdir(); (card/'main.nc').write_bytes(b'ORIGINAL CARD\n'); (card/'unrelated.bin').write_bytes(b'preserve')
    provider = FakeVolumes(card)
    exporter = ExportManager(repo, jobs, mirror, provider)
    draft = drafts.generate(GenerateRequest(prompt='Draw a circle diameter 60'), Event())
    job = jobs.prepare(PreparationRequest(revision_id=draft.revision_id, profile_id=profile.id, profile_revision=profile.revision))
    exporter.select('fixture-card')
    return SimpleNamespace(repo=repo, drafts=drafts, profiles=profiles, profile=profile, jobs=jobs, mirror=mirror,
                           card=card, provider=provider, exporter=exporter, draft=draft, job=job)


def export_request(s, **changes):
    target = s.exporter.find('fixture-card')
    value = dict(target_id=target.id, expected_job_sha256=s.job.gcode_sha256, expected_existing_sha256=target.current_main_sha256,
                 acknowledge_replace=True, computer_owns_card=True, manual_start_understood=True)
    value.update(changes)
    return ExportRequest(**value)


def test_history_survives_restart_and_repairs_missing_or_corrupt_artifacts(system):
    s = system
    assert s.repo.history().total == 1
    reopened = Repository(s.repo.root)
    assert DraftService(repository=reopened).get(s.draft.revision_id).gcode == s.draft.gcode
    path = reopened.artifact_path(s.draft.revision_id)
    for name in ('draft.json', 'drawing.nc', 'preview.svg'):
        (path/name).write_bytes(b'corrupt')
        with pytest.raises(DrawingError, match='damaged'):
            reopened.load(s.draft.revision_id)
        assert reopened.history().items[0].integrity == 'damaged'
        reopened.repair(s.draft.revision_id)
        assert reopened.history().items[0].integrity == 'ok'
    (path/'draft.json').unlink()
    reopened.repair(s.draft.revision_id)
    assert DraftService(repository=reopened).get(s.draft.revision_id).gcode_sha256 == s.draft.gcode_sha256
    with reopened.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1


def test_failed_transaction_and_orphan_recovery_never_claim_a_success(tmp_path, monkeypatch):
    repo = Repository(tmp_path/'data')
    original = repo.connection
    class BrokenInsert:
        def __init__(self, db): self.db = db
        def execute(self, sql, values=()):
            if sql.startswith('INSERT INTO artifacts'): raise sqlite3.OperationalError('injected transaction failure')
            return self.db.execute(sql, values)
    @contextmanager
    def broken():
        with original() as db: yield BrokenInsert(db)
    monkeypatch.setattr(repo, 'connection', broken)
    with pytest.raises(sqlite3.Error):
        DraftService(repository=repo).generate(GenerateRequest(prompt='Draw a circle'), Event())
    monkeypatch.setattr(repo, 'connection', original)
    assert repo.history().total == 0
    assert list(repo.recovery.iterdir())
    orphan = repo.staging/uuid.uuid4().hex; orphan.mkdir(); (orphan/'draft.json').write_bytes(b'uncommitted')
    reopened = Repository(repo.root)
    assert reopened.history().total == 0
    assert reopened.recovery_notices
    assert any((folder/'draft.json').exists() for folder in reopened.recovery.iterdir())


def test_profile_revision_invalidates_preparation_and_auto_sync(system):
    s = system
    s.exporter.arm(AutoSyncRequest(enabled=True, job_id=s.job.id, export=export_request(s)))
    changed = s.profile.model_dump(exclude={'id','revision','version','recorded_at','verification_method'})
    changed['measurement_notes'] += ' updated'
    s.profiles.save(CalibrationSaveRequest(calibration=CalibrationInput(**changed), expected_revision=s.profile.revision), s.profile.id)
    with pytest.raises(DrawingError, match='changed'):
        s.jobs.validate_for_export(s.job.id)
    s.exporter.poll_auto_sync()
    assert s.exporter.auto_state().enabled is False
    assert (s.card/'main.nc').read_bytes() == b'ORIGINAL CARD\n'


def test_verification_requires_real_notes_checks_and_firmware_compatibility(system):
    s = system
    with pytest.raises(ValueError):
        calibration(verified=True, workspace_tested=False)
    with pytest.raises(DrawingError, match='differs'):
        s.profiles.save(CalibrationSaveRequest(calibration=calibration(separation_mm=360)))
    profile = s.profiles.save(CalibrationSaveRequest(calibration=calibration(verified=False), select_for_preparation=True))
    with pytest.raises(DrawingError, match='verify'):
        s.jobs.prepare(PreparationRequest(revision_id=s.draft.revision_id, profile_id=profile.id, profile_revision=profile.revision))


def test_full_segment_rope_minimum_not_just_endpoints(system):
    from backend.app.drawing.gcode import parse
    from backend.app.storage.preparation import validate_physical_path
    profile = calibration(rope_min_mm=225)
    preview = parse('G0 Z5\nG0 X-140.000 Y0.000 Z5\nG1 X0.000 Y100.000 Z0\nG0 Z5\n')
    with pytest.raises(DrawingError, match='rope limits'):
        validate_physical_path(preview, profile)


def test_initial_travel_and_large_drawings_are_validated(system):
    s = system
    large = s.drafts.generate(GenerateRequest(prompt='Draw a circle diameter 400'), Event())
    with pytest.raises(DrawingError, match='outside'):
        s.jobs.prepare(PreparationRequest(revision_id=large.revision_id, profile_id=s.profile.id, profile_revision=s.profile.revision))


def test_mirror_original_backup_and_unrelated_files_survive(system):
    s = system
    (s.mirror/'keep.txt').write_bytes(b'keep')
    first = s.exporter.stage(s.job.id, StageRequest(acknowledge_replace=True, expected_existing_sha256=sha(b'ORIGINAL MIRROR\n')))
    backup = s.repo.root/first.backup
    assert backup.read_bytes() == b'ORIGINAL MIRROR\n'
    assert s.repo.setting('original_mirror_backup') == first.backup
    assert (s.mirror/'main.nc').read_bytes() == s.job.gcode.encode()
    assert (s.mirror/'keep.txt').read_bytes() == b'keep'
    assert json.loads((s.mirror/'PICASSO.JSN').read_text())['gcode_sha256'] == s.job.gcode_sha256
    s.exporter.stage(s.job.id, StageRequest(acknowledge_replace=True, expected_existing_sha256=s.job.gcode_sha256))
    assert backup.read_bytes() == b'ORIGINAL MIRROR\n'


def test_physical_export_is_verified_and_backs_up_original(system):
    s = system
    record = s.exporter.export(s.job.id, export_request(s))
    assert record.status == 'verified' and record.bytes_verified == len(s.job.gcode)
    assert (s.repo.root/record.backup).read_bytes() == b'ORIGINAL CARD\n'
    assert (s.card/'main.nc').read_bytes() == s.job.gcode.encode()
    assert (s.card/'unrelated.bin').read_bytes() == b'preserve'
    assert (s.mirror/'main.nc').read_bytes() == b'ORIGINAL MIRROR\n'


def test_simulation_export_cannot_touch_physical_card_or_mirror(system):
    s = system
    job = s.jobs.prepare(PreparationRequest(revision_id=s.draft.revision_id, mode='simulation'))
    with pytest.raises(DrawingError, match='physical job'):
        s.exporter.export(job.id, export_request(s))
    with pytest.raises(DrawingError, match='Simulation'):
        s.exporter.stage(job.id, StageRequest(acknowledge_replace=True))
    target = s.exporter.create_test()
    record = s.exporter.export(job.id, ExportRequest(target_id=target.id, expected_job_sha256=job.gcode_sha256, acknowledge_replace=True))
    assert record.target_kind == 'test_directory' and record.status == 'verified'
    assert (s.mirror/'main.nc').read_bytes() == b'ORIGINAL MIRROR\n'


@pytest.mark.parametrize('failure', ['readonly','full','permission','temporary_checksum','final_checksum','removal','external_edit','replacement_root'])
def test_failed_copies_never_report_verified_or_overwrite_other_volumes(system, monkeypatch, failure):
    s = system
    request = export_request(s)
    original_write = s.exporter._write_at
    if failure == 'readonly':
        s.provider.writable = False
    elif failure in ('full','permission'):
        def bad(*args): raise OSError(errno.ENOSPC if failure == 'full' else errno.EACCES, 'injected write failure')
        monkeypatch.setattr(s.exporter, '_write_at', bad)
    elif failure in ('temporary_checksum','final_checksum'):
        original_read = s.exporter.read_at
        reads = 0
        def read(fd, name, limit=16_000_000):
            nonlocal reads
            if name == 'main.nc': reads += 1
            if (failure == 'temporary_checksum' and name.endswith('.TMP')) or (failure == 'final_checksum' and name == 'main.nc' and reads >= 3): return b'bad readback'
            return original_read(fd, name, limit)
        monkeypatch.setattr(s.exporter, 'read_at', read)
    else:
        writes = 0
        def changed(fd, name, content, check):
            nonlocal writes
            original_write(fd, name, content, check); writes += 1
            if writes == 1:
                if failure == 'removal': s.provider.online = False
                if failure == 'external_edit': (s.card/'main.nc').write_bytes(b'external change')
                if failure == 'replacement_root':
                    s.card.rename(s.card.with_name('old-mounted-root'))
                    s.card.mkdir(); (s.card/'main.nc').write_bytes(b'NEW VOLUME MUST STAY UNCHANGED')
        monkeypatch.setattr(s.exporter, '_write_at', changed)
    with pytest.raises(DrawingError):
        s.exporter.export(s.job.id, request)
    assert all(record['status'] != 'verified' for record in s.repo.transfers())
    if failure == 'replacement_root': assert (s.card/'main.nc').read_bytes() == b'NEW VOLUME MUST STAY UNCHANGED'
    elif failure == 'external_edit': assert (s.card/'main.nc').read_bytes() == b'external change'
    elif failure != 'final_checksum': assert (s.card/'main.nc').read_bytes() == b'ORIGINAL CARD\n'


def test_symlink_escape_and_external_change_are_rejected(system, tmp_path):
    s = system
    outside = tmp_path/'outside'; outside.write_bytes(b'NEVER CHANGE')
    (s.card/'main.nc').unlink(); (s.card/'main.nc').symlink_to(outside)
    with pytest.raises(DrawingError): s.exporter.export(s.job.id, export_request(s))
    assert outside.read_bytes() == b'NEVER CHANGE'
    path = s.repo.artifact_path(s.draft.revision_id)/'drawing.nc'
    path.unlink(); path.symlink_to(outside)
    with pytest.raises(DrawingError): s.drafts.get(s.draft.revision_id)
    s.repo.repair(s.draft.revision_id)
    assert outside.read_bytes() == b'NEVER CHANGE'


def test_auto_sync_exact_job_reinsertion_and_external_edit_pause(system):
    s = system
    s.exporter.arm(AutoSyncRequest(enabled=True, job_id=s.job.id, export=export_request(s)))
    s.exporter.poll_auto_sync()
    assert s.exporter.auto_state().status == 'verified'
    count = len(s.repo.transfers())
    s.exporter.poll_auto_sync(); assert len(s.repo.transfers()) == count
    s.provider.online = False; s.exporter.poll_auto_sync()
    assert s.exporter.auto_state().status == 'waiting'
    s.provider.online = True; s.provider.generation += 1
    s.exporter.poll_auto_sync(); assert len(s.repo.transfers()) == count + 1
    (s.card/'main.nc').write_bytes(b'EXTERNAL EDIT')
    s.exporter.poll_auto_sync()
    assert not s.exporter.auto_state().enabled
    assert s.exporter.auto_state().status == 'paused_for_review'
    assert (s.card/'main.nc').read_bytes() == b'EXTERNAL EDIT'


def test_restart_marks_in_progress_export_interrupted(system):
    s = system
    original = s.exporter._write_at
    def crash(*args): raise KeyboardInterrupt('injected process interruption')
    s.exporter._write_at = crash
    with pytest.raises(KeyboardInterrupt): s.exporter.export(s.job.id, export_request(s))
    # A hard process crash cannot run the finally handler; emulate the durable journal state.
    record = s.repo.transfers()[0]; record['status'] = 'copying'
    from backend.app.models import TransferRecord
    s.repo.record_transfer(TransferRecord(**record))
    reopened = Repository(s.repo.root)
    assert reopened.transfers()[0]['status'] == 'interrupted'
    assert reopened.recovery_notices
    s.exporter._write_at = original


def test_selection_and_auto_sync_configuration_cannot_race_active_export(system):
    s = system
    with s.exporter.exclusive():
        for operation in (
            lambda: s.exporter.select('fixture-card'),
            lambda: s.exporter.arm(AutoSyncRequest(enabled=False)),
        ):
            with pytest.raises(DrawingError) as error:
                operation()
            assert error.value.code == 'TRANSFER_BUSY'
    s.exporter.arm(AutoSyncRequest(enabled=True, job_id=s.job.id, export=export_request(s)))
    s.exporter.poll_auto_sync()
    s.exporter.arm(AutoSyncRequest(enabled=False))
    s.exporter.poll_auto_sync()
    assert not s.exporter.auto_state().enabled


def test_local_mirror_parent_symlink_is_rejected(system, tmp_path):
    s = system
    outside = tmp_path/'outside'; outside.mkdir()
    mirror = outside/'mirror'; mirror.mkdir(); (mirror/'main.nc').write_bytes(b'UNCHANGED')
    alias = tmp_path/'alias'; alias.symlink_to(outside, target_is_directory=True)
    s.exporter.mirror = alias/'mirror'
    with pytest.raises(DrawingError) as error:
        s.exporter.stage(s.job.id, StageRequest(expected_existing_sha256=sha(b'UNCHANGED'), acknowledge_replace=True))
    assert error.value.code == 'UNSAFE_TARGET'
    assert (mirror/'main.nc').read_bytes() == b'UNCHANGED'


def test_linux_discovery_filters_and_isolates_unsafe_cards(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from backend.app.storage.targets import LinuxTargets
    import backend.app.storage.targets as discovery
    mounted = tmp_path/'mounted'; mounted.mkdir(); (mounted/'main.nc').write_bytes(b'FILE')
    unsafe = tmp_path/'unsafe'; unsafe.mkdir(); (unsafe/'main.nc').symlink_to(mounted/'main.nc')
    other = tmp_path/'internal'; other.mkdir()
    tree = {'blockdevices': [
        {'path':'/dev/fakeusb', 'tran':'usb', 'rm':False, 'children':[
            {'path':'/dev/fakeusb1','fstype':'vfat','uuid':'FAT-ID','mountpoints':[str(mounted)]},
            {'path':'/dev/fakeusb2','fstype':'vfat','uuid':'UNSAFE','mountpoints':[str(unsafe)]},
        ]},
        {'path':'/dev/internal','fstype':'vfat','uuid':'INTERNAL','mountpoints':[str(other)]},
    ]}
    monkeypatch.setattr(discovery.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(tree)))
    monkeypatch.setattr(discovery.os.path, 'ismount', lambda path: True)
    targets, error = LinuxTargets().discover()
    assert error is None and len(targets) == 2
    good = next(item for item in targets if item.volume_uuid == 'FAT-ID')
    bad = next(item for item in targets if item.volume_uuid == 'UNSAFE')
    assert good.writable and good.current_main_sha256 == sha(b'FILE')
    assert not bad.writable and 'Cannot inspect' in bad.reason


def test_consecutive_sd_jobs_require_origin_again_instead_of_inheriting_prior_endpoint(system):
    s = system
    first_end = s.job.preview.segments[-1].end
    assert tuple(first_end) != (0, 0)
    s.exporter.export(s.job.id, export_request(s))
    draft = s.drafts.generate(GenerateRequest(prompt='Draw a rectangle 50 x 30 mm'), Event())
    second = s.jobs.prepare(PreparationRequest(revision_id=draft.revision_id, profile_id=s.profile.id, profile_revision=s.profile.revision))
    assert tuple(second.preview.segments[-1].end) != tuple(first_end)
    assert second.manual_origin_required and tuple(second.expected_start_mm) == (0, 0)
    assert tuple(second.preview.segments[0].start) == (0, 0)
    assert second.hardware_execution_verified is False
    assert s.job.gcode_sha256 == s.jobs.get(s.job.id).gcode_sha256
