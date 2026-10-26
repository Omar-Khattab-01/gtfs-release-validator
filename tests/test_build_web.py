import hashlib
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

from gtfs_validator import build_web
from gtfs_validator.web import ValidatorHandler
from test_validator import write_feed


class BuildWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {
            'GTFS_VALIDATOR_BUILD_DIR': str(self.root/'history'),
            'GTFS_VALIDATOR_CACHE_DIR': str(self.root/'cache')})
        self.environment.start()
        build_web.JOBS.clear()
        self.cad = self.root/'CAD export.zip'; self.bus = self.root/'HASTUS export.zip'
        write_feed(self.cad); write_feed(self.bus)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ValidatorHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        build_web.JOBS.clear(); self.environment.stop(); self.temp.cleanup()

    def request(self, path, payload=None, header=True):
        headers = {'Content-Type':'application/json'}
        if header: headers['X-GTFS-Validator'] = '1'
        req = urllib.request.Request(self.base+path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try: response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as error: response = error
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if 'application/json' in response.headers.get('Content-Type','') else raw

    def payload(self, **extra):
        return {'cad_path':f'"{self.cad}"', 'hastus_path':str(self.bus), 'start_date':'2026-10-01',
                'end_date':'2026-10-31', 'output_directory':str(self.root/'outputs'), **extra}

    def completed(self, ident):
        limit = time.monotonic()+15
        while time.monotonic() < limit:
            status, job = self.request('/api/builds/'+ident)
            self.assertEqual(200, status)
            if job['status'] not in build_web.ACTIVE: return job
            time.sleep(.04)
        self.fail('Background build did not finish')

    def test_browser_to_api_build_download_and_restart_history(self):
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.cad,self.bus)]
        status, job = self.request('/api/builds', self.payload())
        self.assertEqual(202, status)
        ident = job['id']; job = self.completed(ident)
        self.assertEqual('complete', job['status'], job['error'])
        self.assertEqual(1, job['result']['summary']['counts']['bus_trips'])
        self.assertNotIn('crosswalk', json.dumps(job))
        status, content = self.request(f'/api/builds/{ident}/download/zip')
        self.assertEqual(200, status)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertTrue(all(i.external_attr>>16 == 0o100644 for i in archive.infolist()))
        status, receipt = self.request(f'/api/builds/{ident}/download/receipt')
        self.assertTrue(receipt['source_only_builder']); self.assertEqual(1,len(receipt['crosswalk']))
        status, csv = self.request(f'/api/builds/{ident}/download/reviews')
        self.assertIn(b'rail_not_supplied', csv)
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.cad,self.bus)])
        build_web.JOBS.clear()  # Exercise the disk-recovery path used on server restart.
        status, history = self.request('/api/builds')
        self.assertEqual(ident, history['builds'][0]['id']); self.assertIsNone(history['active_id'])
        status, recovered = self.request('/api/builds/'+ident)
        self.assertEqual(job['result'], recovered['result'])
        self.assertEqual(200, self.request(f'/api/builds/{ident}/download/zip')[0])

    def test_preflight_and_local_request_protection_never_write_over_existing_files(self):
        self.assertEqual(403, self.request('/api/builds', self.payload(), header=False)[0])
        for invalid in [{'cad_path':''}, {'end_date':'2026-09-30'}, {'output_name':'../escape.zip'}, {'output_name':'CON.zip'}]:
            with self.subTest(invalid=invalid): self.assertEqual(400, self.request('/api/builds', self.payload(**invalid))[0])
        directory = self.root/'outputs'; directory.mkdir()
        target = directory/'existing.zip'; target.write_bytes(b'original')
        self.assertEqual(400,self.request('/api/builds',self.payload(output_name='existing.zip'))[0])
        self.assertEqual(b'original',target.read_bytes()); self.assertFalse(build_web.JOBS)

    def test_second_build_is_rejected_while_first_is_running(self):
        original = build_web.build_release; entered = threading.Event(); release = threading.Event()
        def delayed(*args, **kwargs):
            entered.set(); release.wait(5)
            return original(*args, **kwargs)
        with patch('gtfs_validator.build_web.build_release', side_effect=delayed):
            try:
                status, first = self.request('/api/builds', self.payload())
                self.assertEqual(202,status); self.assertTrue(entered.wait(5))
                status, second = self.request('/api/builds', self.payload())
                self.assertEqual(400,status); self.assertIn('already running',second['error'])
            finally: release.set()
            self.assertEqual('complete',self.completed(first['id'])['status'])

    def test_generation_failure_is_visible_and_does_not_block_a_retry(self):
        bad = self.root/'bad.zip'; bad.write_bytes(b'not a ZIP')
        status, job = self.request('/api/builds', self.payload(hastus_path=str(bad)))
        job = self.completed(job['id'])
        self.assertEqual('failed',job['status']); self.assertTrue(job['error'])
        self.assertFalse(Path(job['request']['output_path']).exists())
        self.assertEqual(404,self.request(f"/api/builds/{job['id']}/download/zip")[0])
        status, retry = self.request('/api/builds', self.payload())
        self.assertEqual(202,status); self.assertEqual('complete',self.completed(retry['id'])['status'])

    def test_reference_is_independent_and_failed_comparison_keeps_the_draft(self):
        bad = self.root/'reference.zip'; bad.write_bytes(b'bad reference')
        status, job = self.request('/api/builds', self.payload(reference_path=str(bad)))
        job = self.completed(job['id'])
        self.assertEqual('complete',job['status'])
        self.assertEqual('failed',job['result']['comparison']['status'])
        self.assertEqual(200,self.request(f"/api/builds/{job['id']}/download/zip")[0])
        self.assertEqual(404,self.request(f"/api/builds/{job['id']}/download/comparison")[0])
        status, second = self.request('/api/builds', self.payload(reference_path=job['result']['output']))
        second = self.completed(second['id'])
        self.assertEqual('complete',second['result']['comparison']['status'])
        self.assertTrue(second['result']['comparison']['equivalent'])
        self.assertEqual(200,self.request(f"/api/builds/{second['id']}/download/comparison")[0])

    def test_interrupted_build_is_recovered_without_claiming_completion(self):
        folder = build_web.history_root()/'abcdef012345'
        folder.mkdir(parents=True)
        job = build_web.BuildJob('abcdef012345',self.payload(),folder,status='running')
        job.save()
        recovered = build_web.get_build(job.id)
        self.assertEqual('interrupted',recovered['status']); self.assertIn('server stopped',recovered['error'])

    def test_native_picker_returns_paths_and_cancel_without_uploading(self):
        with patch('gtfs_validator.build_web.pick_path', return_value={'path':str(self.cad)}) as picker:
            status, data = self.request('/api/builds/pick',{'kind':'zip'})
            self.assertEqual(200,status); self.assertEqual(str(self.cad),data['path']); picker.assert_called_once_with('zip')
        with patch('gtfs_validator.build_web.subprocess.run') as run:
            run.return_value.returncode = 0; run.return_value.stdout = '{"path":""}'
            self.assertEqual({'path':''},build_web.pick_path('folder'))
            self.assertNotIn('shell',run.call_args.kwargs)
        with self.assertRaises(ValueError): build_web.pick_path('arbitrary-command')
        self.assertEqual(404,self.request('/api/builds/../../download/zip')[0])


if __name__ == '__main__': unittest.main()
