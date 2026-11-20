"""Persistent path-to-content fingerprints for reopening unchanged local exports."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from .cache_store import cache_root

LOCK = threading.RLock()


def _signature(path):
    info = path.stat()
    return [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_dev, info.st_ino]


def _read():
    try:
        data = json.loads((cache_root() / 'source-paths.json').read_text(encoding='utf-8'))
        if data.get('version') == 1 and isinstance(data.get('sources'), dict):
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return {'version': 1, 'sources': {}}


def _write(data):
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='source-paths-', dir=root) as folder:
        staged = Path(folder) / 'paths.json'
        staged.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        staged.replace(root / 'source-paths.json')


def _sample(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        digest.update(stream.read(65536))
        stream.seek(max(0, path.stat().st_size - 65536))
        digest.update(stream.read(65536))
    return digest.hexdigest()


def _hash_source(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(path, *, verify=False):
    resolved = Path(path).expanduser().resolve()
    key = os.path.normcase(str(resolved))
    with LOCK:
        before = _signature(resolved)
        sample = _sample(resolved)
        data = _read()
        saved = data['sources'].get(key, {})
        valid = (isinstance(saved, dict) and saved.get('signature') == before
                 and saved.get('sample') == sample
                 and re.fullmatch('[0-9a-f]{64}', str(saved.get('sha256', ''))))
        digest = saved['sha256'] if valid and not verify else _hash_source(resolved)
        if _signature(resolved) != before:
            raise ValueError('Export changed while checking its saved index. Try reopening it again.')
        record = {'path': str(resolved), 'signature': before, 'sample': sample, 'sha256': digest}
        if record != saved:
            data['sources'][key] = record
            try:
                _write(data)
            except OSError:
                pass  # A read-only cache still permits ordinary validation.
        return {'path': str(resolved), 'sha256': digest}


def saved_index(path, *, remember=False):
    if not cache_root().is_dir() or not any(cache_root().glob('index-v2-*.sqlite')):
        return None
    if not remember:
        key = os.path.normcase(str(Path(path).expanduser().resolve()))
        with LOCK:
            if key not in _read()['sources']:
                return None
    value = fingerprint(path)
    candidate = cache_root() / f"index-v2-{value['sha256']}.sqlite"
    return candidate if candidate.is_file() and not candidate.is_symlink() else None


def paths_by_index():
    result = {}
    with LOCK:
        for record in _read()['sources'].values():
            if not isinstance(record, dict) or not re.fullmatch('[0-9a-f]{64}', str(record.get('sha256', ''))):
                continue
            name = f"index-v2-{record['sha256']}.sqlite"
            if isinstance(record.get('path'), str):
                result.setdefault(name, []).append(record['path'])
    return result


def forget_indexes(names):
    with LOCK:
        data = _read()
        data['sources'] = {key: record for key, record in data['sources'].items()
                           if isinstance(record, dict) and f"index-v2-{record.get('sha256', '')}.sqlite" not in names}
        try:
            _write(data)
        except OSError:
            pass
