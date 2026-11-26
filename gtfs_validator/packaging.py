"""Read-only ZIP metadata review and optional temporary extraction."""
import os
import stat
import tempfile
import zipfile
from pathlib import Path

POSIX_PERMISSIONS = os.name != 'nt'

from .archive import is_unsafe_name, MAX_MEMBER_BYTES, MAX_TOTAL_BYTES


def packaging_report(path, extract=False):
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        unsafe = any(is_unsafe_name(item.filename) or item.filename.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{n}' for n in range(1,10)),*(f'LPT{n}' for n in range(1,10))} for item in members)
        oversized = sum(item.file_size for item in members) > MAX_TOTAL_BYTES or any(item.file_size > MAX_MEMBER_BYTES for item in members)
        if extract and (unsafe or oversized or any(stat.S_IFMT(item.external_attr >> 16) not in {0, stat.S_IFREG} for item in members)):
            raise ValueError('Unsafe archive layout, member type or size; extraction was not attempted.')
        rows = []
        for item in members:
            stored = (item.external_attr >> 16) & 0xFFFF
            known = item.create_system == 3 or bool(stored)
            mode = stat.S_IMODE(stored) if known else None
            rows.append({'file': item.filename, 'bytes': item.file_size,
                         'stored_mode': f'{mode:04o}' if mode is not None else None,
                         'flagged': mode == 0o600, 'extracted_mode': None})
        result = {'path': str(path), 'files': rows, 'extraction_tested': False,
                  'posix_permissions': POSIX_PERMISSIONS, 'flagged_count': sum(row['flagged'] for row in rows)}
        if extract:
            # Never apply stored Unix modes: record what a normal Python extraction produces.
            # Stored 0600 is checked separately, even if extraction creates a readable file.
            with tempfile.TemporaryDirectory(prefix='gtfs-package-check-') as folder:
                for item, row in zip(members, rows):
                    output = Path(archive.extract(item, folder))
                    if POSIX_PERMISSIONS:
                        row['extracted_mode'] = f'{stat.S_IMODE(output.stat().st_mode):04o}'
                    row['extracted_bytes'] = output.stat().st_size
            result['extraction_tested'] = True
        return result
