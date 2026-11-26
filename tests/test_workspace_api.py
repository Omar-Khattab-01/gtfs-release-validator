import hashlib
import io
import json
import stat
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from gtfs_validator import __version__
from gtfs_validator.engine import validate_feed
from gtfs_validator.file_picker import pick_file
from gtfs_validator.packaging import packaging_report
from gtfs_validator.web import JOBS, Job, ValidatorHandler, _run_job
from test_validator import FILES, write_feed


class PackagingTests(unittest.TestCase):
    def test_only_stored_0600_is_flagged_and_extraction_keeps_source_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'feed.zip'
            for mode in (0o644, 0o666, 0o640, 0o600):
                write_feed(path, mode=mode)
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                result = packaging_report(path, True)
                self.assertTrue(result['extraction_tested'])
                self.assertEqual(len(FILES) if mode==0o600 else 0, result['flagged_count'])
                self.assertEqual({f'{mode:04o}'}, {row['stored_mode'] for row in result['files']})
                self.assertEqual({len(text.encode()) for text in FILES.values()}, {row['extracted_bytes'] for row in result['files']})
                self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
                findings = validate_feed(path).findings
                self.assertEqual(mode==0o600, any(item.rule_id=='PKG009' for item in findings))
                self.assertFalse(any(item.rule_id=='PKG018' for item in findings))

    def test_windows_metadata_absence_is_not_a_permission_issue(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'feed.zip'
            with zipfile.ZipFile(path,'w') as archive:
                for name, value in FILES.items():
                    info=zipfile.ZipInfo(name);info.create_system=0;info.external_attr=0x20
                    archive.writestr(info,value)
            with patch('gtfs_validator.packaging.POSIX_PERMISSIONS',False):
                result=packaging_report(path,True)
            self.assertEqual(0,result['flagged_count'])
            self.assertTrue(all(row['stored_mode'] is None and row['extracted_mode'] is None for row in result['files']))
            self.assertTrue(result['extraction_tested'])

    def test_unsafe_members_are_never_extracted(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'unsafe.zip'
            for name, mode in [('../outside.txt',stat.S_IFREG),('CON.txt',stat.S_IFREG),('link.txt',stat.S_IFLNK)]:
                with self.subTest(name=name), zipfile.ZipFile(path,'w') as archive:
                    info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=(mode|0o644)<<16
                    archive.writestr(info,'data')
                with self.assertRaises(ValueError):packaging_report(path,True)


class PickerTests(unittest.TestCase):
    def test_native_picker_returns_selected_or_cancelled_path_without_shell(self):
        for path in [r'C:\GTFS\feed.zip','']:
            with patch('gtfs_validator.file_picker.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps({'path':path}))) as run:
                self.assertEqual(path,pick_file('zip')['path'])
                self.assertEqual('gtfs_validator.file_picker',run.call_args.args[0][2])
                self.assertNotIn('shell',run.call_args.kwargs)
        with self.assertRaises(ValueError):pick_file('unsupported')

    def test_missing_tk_has_an_actionable_fallback(self):
        with patch('gtfs_validator.file_picker.subprocess.run',return_value=subprocess.CompletedProcess([],1,'')):
            with self.assertRaisesRegex(ValueError,'Paste the file path'):pick_file()


class WorkspaceApiTests(unittest.TestCase):
    def test_summary_polling_picker_headers_packaging_and_embedded_viewer(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'feed.zip';write_feed(path)
            job=Job('workspace-test','','',str(path));_run_job(job)
            self.assertEqual('complete',job.status);self.assertEqual(100,job.progress_percent)
            self.assertEqual(__version__,job.report['tool_version'])
            JOBS[job.id]=job
            with ThreadingHTTPServer(('127.0.0.1',0),ValidatorHandler) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base=f'http://127.0.0.1:{server.server_port}'
                def request(url, data=None, header=True):
                    req=urllib.request.Request(base+url,data=json.dumps(data).encode() if data is not None else None,
                                               headers={'Content-Type':'application/json',**({'X-GTFS-Validator':'1'} if header else {})})
                    return urllib.request.urlopen(req)
                try:
                    with request(f'/api/runs/{job.id}?summary=1') as response:
                        summary=json.load(response)
                    self.assertNotIn('report',summary)
                    self.assertEqual(100,summary['progress_percent'])
                    self.assertIn('report',json.load(request(f'/api/runs/{job.id}')))
                    data=json.load(request(f'/api/runs/{job.id}/packaging?source=final&extract=1'))
                    self.assertTrue(data['extraction_tested']);self.assertEqual(0,data['flagged_count'])
                    with patch('gtfs_validator.web.pick_file',return_value={'path':str(path)}) as picker:
                        self.assertEqual(str(path),json.load(request('/api/pick-file',{'kind':'zip'}))['path'])
                        picker.assert_called_once_with('zip')
                    with self.assertRaises(urllib.error.HTTPError) as error:request('/api/pick-file',{'kind':'zip'},False)
                    self.assertEqual(403,error.exception.code)
                    with request('/file-viewer/') as response:
                        self.assertEqual('SAMEORIGIN',response.headers['X-Frame-Options'])
                    with request('/') as response:
                        self.assertEqual('DENY',response.headers['X-Frame-Options'])
                        html=response.read().decode();self.assertIn('GTFS Validator',html);self.assertNotIn('Offline processing',html)
                finally:
                    server.shutdown();thread.join();JOBS.pop(job.id,None)


if __name__=='__main__':unittest.main()
