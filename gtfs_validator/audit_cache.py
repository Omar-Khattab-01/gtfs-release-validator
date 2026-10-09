"""Reuse completed audits only after fingerprinting inputs, policy and code."""
import hashlib
import importlib.metadata
import json
import os
import platform
import tempfile
from datetime import date
from pathlib import Path
from . import cache_store
from .final_checks import DEFAULT_JAR, PACKAGE
from .java_runtime import find_java


def fingerprint(path: str | Path) -> dict:
    resolved = Path(path).expanduser().resolve()
    before = resolved.stat()
    digest = hashlib.sha256()
    with resolved.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    after = resolved.stat()
    if (before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_size,after.st_mtime_ns,after.st_ctime_ns):
        raise ValueError('Input changed while checking saved results')
    return {'path':str(resolved),'sha256':digest.hexdigest()}


def identity(job) -> dict:
    value = {'schema':1, 'today':date.today().isoformat(), 'platform':platform.system(),
             'validation_date':job.validation_date,'release_policy':job.release_policy,
             'run_agency':job.run_agency,'run_mobility':job.run_mobility,
             'feeds':[fingerprint(path) if path else None for path in (job.clevercad_path,job.hastus_path,job.final_path)],
             'code':[fingerprint(path) for path in sorted(PACKAGE.glob('*.py'))]}
    if job.final_path and job.run_agency:
        value['reference'] = fingerprint(job.sort_reference or PACKAGE / 'routes_sort_order_list.csv')
        value['dependencies'] = {}
        for name in ('pandas','tzdata'):
            try:
                value['dependencies'][name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                value['dependencies'][name] = 'missing'
    if job.final_path and job.run_mobility:
        value['jar'] = fingerprint(job.mobility_jar or DEFAULT_JAR)
        java = find_java()
        value['java'] = fingerprint(java) if java else None
    return value


def destination(value: dict) -> Path:
    digest = hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    return cache_store.cache_root() / f'audit-v1-{digest}.json'


def load(value: dict) -> dict | None:
    path = destination(value)
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 128 * 1024**2:
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('identity') != value or not isinstance(data.get('report'),dict):
            return None
        report = data['report']
        if not isinstance(report.get('findings'),list) or not isinstance(report.get('stats'),dict):
            return None
        if not all(key in report for key in ('counts','files','decision','source_path','tool_version','profile')):
            return None
        final = data.get('final_validation')
        if value['feeds'][2] and (not isinstance(final,dict) or set(final) != {'technical','agency','mobility'}):
            return None
        if final and any(not isinstance(engine,dict) or engine.get('status') not in {'complete','not_requested'} for engine in final.values()):
            return None
        os.utime(path,None)
        return data
    except (OSError,ValueError,AttributeError):
        return None


def save(value: dict, job) -> str:
    if job.final_validation and any(engine.get('status') not in {'complete','not_requested'} for engine in job.final_validation.values()):
        return 'Not saved: a validation engine did not complete; next run will retry.'
    if identity(job) != value:
        return 'Not saved: an input changed during validation.'
    path = destination(value)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    data = json.dumps({'identity':value,'report':job.report,'final_validation':job.final_validation},ensure_ascii=False).encode()
    existing = sum(item['bytes'] for item in cache_store.entries())
    if len(data) > 128 * 1024**2 or existing + len(data) > cache_store.MAX_BYTES:
        return 'Not saved: saved-result storage budget exceeded.'
    with tempfile.TemporaryDirectory(prefix='audit-publish-',dir=path.parent) as staging:
        staged = Path(staging)/'report.json'
        staged.write_bytes(data)
        os.replace(staged,path)
    return 'Saved audit for reopening today (input fingerprints verified).'
