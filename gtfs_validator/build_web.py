"""Local background builds and durable, compact build history for the web UI."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import csv
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid

from .cache_store import cache_root
from .input_paths import normalize_path
from .release_builder import DEFAULT_POLICY, build_release, load_policy
from .release_compare import compare_releases

ACTIVE = {'queued', 'running', 'comparing'}
JOBS = {}
LOCK = threading.RLock()
PICKER_LOCK = threading.Lock()
REVIEW_LABELS = {
    'unmatched_trip': 'Trips without a HASTUS match',
    'partial_dates': 'Trips with uncovered service dates',
    'lower_similarity_trip': 'Changed patterns requiring review',
    'conflicting_trip_metadata': 'Conflicting trip attributes',
    'conflicting_stop_metadata': 'Conflicting stop attributes',
    'unsupported_source_table': 'Source tables without a merge rule',
    'unsupported_source_columns': 'Source columns without a merge rule',
    'omitted_table': 'Nonempty tables excluded by policy',
    'rail_not_supplied': 'Rail export not supplied',
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def history_root():
    override = os.environ.get('GTFS_VALIDATOR_BUILD_DIR')
    return Path(override).expanduser().resolve() if override else cache_root().parent / 'build-history'


def defaults():
    policy = load_policy(DEFAULT_POLICY)
    return {'output_directory': str(cache_root().parent / 'merged-exports'), 'policy': policy}


@dataclass
class BuildJob:
    id: str
    request: dict
    folder: Path
    status: str = 'queued'
    stage: str = 'sources'
    progress: str = 'Waiting to read source exports'
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    error: str | None = None
    result: dict | None = None
    log: list = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def public(self):
        with self.lock:
            return {key: getattr(self, key) for key in (
                'id', 'request', 'status', 'stage', 'progress', 'created_at',
                'updated_at', 'error', 'result', 'log')}

    def save(self):
        # Only our own small status file is replaced, never a supplied archive.
        with self.lock:
            temporary = self.folder / 'status.tmp'
            temporary.write_text(json.dumps(self.public(), ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.folder / 'status.json')

    def update(self, message, stage=None, status=None):
        with self.lock:
            self.progress = message
            if stage: self.stage = stage
            if status: self.status = status
            self.updated_at = now()
            self.log.append({'time': self.updated_at, 'message': message})
            self.log = self.log[-120:]
            self.save()


def _read_job(ident):
    if not re.fullmatch(r'[0-9a-f]{12}', ident):
        raise ValueError('Unknown build')
    if ident in JOBS:
        return JOBS[ident]
    folder = history_root() / ident
    try:
        data = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
        job = BuildJob(folder=folder, **data)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError('Unknown or unreadable build') from exc
    if job.status in ACTIVE:
        if job.result and job.request.get('reference_path'):
            job.result['comparison'] = {'status': 'interrupted', 'message': 'The server stopped before the comparison finished.'}
        job.error = 'The local server stopped before this build finished. Start a new build with a new output name.'
        job.update(job.error, status='interrupted')
    JOBS[ident] = job
    return job


def get_build(ident):
    with LOCK:
        return _read_job(ident).public()


def list_builds():
    with LOCK:
        root = history_root()
        paths = sorted(root.glob('*/status.json'), key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []
        for path in paths[:25]:
            try: _read_job(path.parent.name)
            except ValueError: continue
        values = [j.public() for j in JOBS.values()]
    values.sort(key=lambda j: j['created_at'], reverse=True)
    return {'defaults': defaults(), 'active_id': next((j['id'] for j in values if j['status'] in ACTIVE), None),
            'builds': [{k: j[k] for k in ('id', 'status', 'created_at', 'progress', 'request')} for j in values[:25]]}


def _source(value, label, required=False):
    text = normalize_path(value or '')
    if not text:
        if required: raise ValueError('Select the ' + label)
        return ''
    path = Path(text).expanduser().resolve()
    if not path.is_file(): raise ValueError(label + ' file was not found: ' + str(path))
    return str(path)


def start_build(payload):
    request = {key: _source(payload.get(key), label, required) for key, label, required in (
        ('cad_path', 'CleverCAD ZIP', True), ('hastus_path', 'HASTUS bus ZIP', True),
        ('rail_path', 'HASTUS rail ZIP', False), ('reference_path', 'reference final ZIP', False),
        ('policy_path', 'custom policy JSON', False), ('sort_reference', 'route-sort CSV', False))}
    for key in ('start_date', 'end_date'):
        try: request[key] = date.fromisoformat(str(payload.get(key, ''))).strftime('%Y%m%d')
        except ValueError: raise ValueError('Choose valid publication start and end dates')
    if request['start_date'] > request['end_date']: raise ValueError('Publication end must be on or after its start')
    load_policy(request['policy_path'] or DEFAULT_POLICY)
    directory = normalize_path(payload.get('output_directory') or defaults()['output_directory'])
    directory = Path(directory).expanduser().resolve()
    if directory.exists() and not directory.is_dir(): raise ValueError('The save folder is not a directory')
    ident = uuid.uuid4().hex[:12]
    name = str(payload.get('output_name') or '').strip() or f"merged-{request['start_date']}-{ident}.zip"
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,149}\.zip', name, re.I):
        raise ValueError('Use a ZIP filename containing letters, numbers, spaces, dots, underscores or hyphens')
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('This filename is reserved on Windows')
    output = directory / name
    if any(p.exists() for p in (output, output.with_suffix('.report.json'), output.with_suffix('.comparison.json'))):
        raise ValueError('This output name is already used. Choose a new name; existing files are kept.')
    if str(output) in request.values(): raise ValueError('Output cannot replace an input file')
    request['output_path'] = str(output)
    with LOCK:
        if any(j.status in ACTIVE for j in JOBS.values()):
            raise ValueError('A merge is already running. Wait for it to finish before starting another.')
        folder = history_root() / ident
        folder.mkdir(parents=True, exist_ok=False)
        job = BuildJob(ident, request, folder)
        # Freeze policy content for this build, even when a custom path is used.
        (folder / 'policy.json').write_text(json.dumps(load_policy(request['policy_path'] or DEFAULT_POLICY), indent=2), encoding='utf-8')
        job.save()
        JOBS[ident] = job
        threading.Thread(target=_run_build, args=(job,), daemon=True).start()
    return job.public()


def _summary(receipt):
    grouped = defaultdict(list)
    for warning in receipt['warnings']: grouped[warning['kind']].append(warning)
    validation = dict(receipt['validation'])
    validation['findings'] = validation.get('findings', [])[:20]
    return {'counts': receipt['counts'], 'validation': validation,
            'policy': receipt['policy'], 'changes': receipt['changes'],
            'excluded_trip_count': len(receipt['excluded_trips']),
            'review_groups': [{'kind': kind, 'title': REVIEW_LABELS.get(kind, kind.replace('_',' ').capitalize()),
                               'count': len(items), 'examples': items[:5]} for kind, items in grouped.items()],
            'archive_verification': receipt['archive_verification'], 'sha256': receipt['output_sha256']}


def _run_build(job):
    request = job.request
    def progress(message):
        stage = job.stage
        if message.startswith('Matched'): stage = 'matching'
        elif 'Applying source' in message or 'Writing merged' in message: stage = 'building'
        elif 'Checking ZIP' in message or 'validation' in message: stage = 'verifying'
        job.update(message, stage=stage, status='running')
    try:
        job.update('Reading source archives and calendars', stage='sources', status='running')
        result = build_release(request['cad_path'], request['hastus_path'], request['output_path'],
            rail_path=request['rail_path'] or None, start_date=request['start_date'], end_date=request['end_date'],
            policy_path=job.folder / 'policy.json', sort_reference=request['sort_reference'] or None,
            allow_draft=True, progress=progress)
        receipt = json.loads(Path(result['receipt']).read_text(encoding='utf-8'))
        with (job.folder / 'review-items.csv').open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['issue_type', 'message', 'trip_id', 'source', 'file', 'field', 'details'])
            for warning in receipt['warnings']:
                cells = [warning['kind'], warning['message'], warning.get('trip_id',''), warning.get('source',''),
                         warning.get('file',''), warning.get('field',''), json.dumps(warning, ensure_ascii=False)]
                writer.writerow(["'"+str(v) if str(v).lstrip().startswith(('=','+','-','@')) else v for v in cells])
        job.result = {**result, 'summary': _summary(receipt), 'comparison': {'status': 'pending' if request['reference_path'] else 'not_requested'}}
        job.save()
        if request['reference_path']:
            job.update('Comparing the generated draft with the reference final', stage='comparing', status='comparing')
            try:
                comparison = compare_releases(result['output'], request['reference_path'], progress=lambda message: job.update(message))
                path = Path(result['output']).with_suffix('.comparison.json')
                with path.open('x', encoding='utf-8') as stream: json.dump(comparison, stream, ensure_ascii=False, indent=2)
                job.result['comparison'] = {key: comparison[key] for key in ('equivalent', 'tables', 'candidate_only_members', 'reference_only_members')}
                job.result['comparison']['status'] = 'complete'
            except Exception as exc:
                job.result['comparison'] = {'status': 'failed', 'message': str(exc)}
        job.update('Draft ready. Review its findings before publication.', stage='ready', status='complete')
    except Exception as exc:
        job.error = str(exc)
        job.update('Build stopped: ' + str(exc), status='failed')


def artifact(ident, kind):
    job = get_build(ident)
    result = job.get('result')
    if not result: raise ValueError('Build artifacts are not ready')
    output = Path(result['output'])
    paths = {'zip': output, 'receipt': Path(result['receipt']),
             'reviews': history_root() / ident / 'review-items.csv'}
    if result['comparison']['status'] == 'complete': paths['comparison'] = output.with_suffix('.comparison.json')
    path = paths.get(kind)
    if path is None or not path.is_file(): raise ValueError('This build artifact is unavailable')
    return path


def pick_path(kind):
    if kind not in {'zip', 'folder', 'policy', 'csv'}: raise ValueError('Unknown file-picker type')
    if not PICKER_LOCK.acquire(blocking=False): raise ValueError('A file picker is already open. Complete or cancel that window first.')
    try:
        result = subprocess.run([sys.executable, '-m', 'gtfs_validator.local_picker', kind],
                                capture_output=True, text=True, encoding='utf-8', timeout=300)
        if result.returncode:
            raise ValueError('The native file picker is unavailable. Paste the full path instead.')
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError('The file picker could not finish. Paste the full path instead.') from exc
    finally:
        PICKER_LOCK.release()
