"""Linux removable-volume discovery. No mounting, formatting or device writes."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

from ..models import StorageTarget
from ..drawing.errors import DrawingError
from .repository import read_regular, sha


def instance(path: Path):
    info = path.stat()
    mount = ''
    if sys.platform == 'linux':
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            fields = line.split()
            decoded = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), fields[4])
            if decoded == str(path):
                mount = fields[0]
                break
    return f'{info.st_dev}:{info.st_ino}:{mount}'


def main_hash(path: Path):
    try:
        return sha(read_regular(path / 'main.nc'))
    except FileNotFoundError:
        return None


class LinuxTargets:
    def discover(self):
        if sys.platform != 'linux':
            return [], 'Physical mount discovery is implemented for Linux. Test-directory export remains available.'
        try:
            output = subprocess.run(['lsblk', '--json', '--tree', '--output', 'PATH,TYPE,RM,RO,FSTYPE,UUID,LABEL,MOUNTPOINTS,TRAN'],
                                    check=True, capture_output=True, text=True, timeout=3)
            devices = json.loads(output.stdout)['blockdevices']
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return [], f'Removable-volume discovery is unavailable: {type(exc).__name__}.'
        targets = []
        def walk(nodes, removable=False):
            for node in nodes:
                removable_here = removable or node.get('rm') in (True, 1, '1') or node.get('tran') == 'usb'
                if removable_here:
                    for mount in node.get('mountpoints') or []:
                        if not mount:
                            continue
                        path = Path(mount).absolute()
                        filesystem = node.get('fstype') or 'unknown'
                        volume = node.get('uuid') or ''
                        writable = node.get('ro') not in (True, 1, '1') and filesystem in ('vfat', 'msdos') and bool(volume)
                        reason = 'Mounted FAT card; select explicitly before export.' if writable else 'A writable FAT16/FAT32 volume with a stable UUID is required.'
                        try:
                            if path.is_symlink() or not path.is_dir() or not os.path.ismount(path):
                                continue
                            signature = instance(path)
                            current = main_hash(path)
                            if os.statvfs(path).f_flag & getattr(os, 'ST_RDONLY', 1):
                                writable = False; reason = 'Mounted read-only.'
                        except (OSError, ValueError, DrawingError) as exc:
                            signature, current, writable = '', None, False
                            reason = f'Cannot inspect the mounted card: {type(exc).__name__}.'
                        identity = sha(f'{volume}|{path}'.encode())[:32]
                        targets.append(StorageTarget(id=identity, label=node.get('label') or node.get('path') or 'Removable card',
                                                     path=str(path), kind='physical_card', filesystem=filesystem, volume_uuid=volume,
                                                     instance=signature, available=True, writable=writable, reason=reason,
                                                     current_main_sha256=current))
                walk(node.get('children') or [], removable_here)
        walk(devices)
        return targets, None


def test_target(path: Path):
    return StorageTarget(id='test-' + sha(str(path).encode())[:24], label='App-owned test card — not physical hardware',
                         path=str(path), kind='test_directory', filesystem='test-directory', volume_uuid='test-only',
                         instance=instance(path), available=True, writable=True,
                         reason='Writes only to data/test-card; cannot stand in for a physical-card check.', current_main_sha256=main_hash(path))
