from http.server import ThreadingHTTPServer
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

from gtfs_validator.feed_index import clear_indexes
from gtfs_validator.web import JOBS, ValidatorHandler
from test_validator import write_feed


class HeadwayApiTests(unittest.TestCase):
    def test_inspect_route_headways_reopen_and_offload_through_http(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GTFS_VALIDATOR_CACHE_DIR':folder}):
            path = Path(folder)/'source.zip'
            write_feed(path)
            original = path.read_bytes()
            server = ThreadingHTTPServer(('127.0.0.1',0),ValidatorHandler)
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            def request(endpoint,payload=None):
                data = json.dumps(payload).encode() if payload is not None else None
                req = urllib.request.Request(base+endpoint,data=data,
                    headers={'Content-Type':'application/json','X-GTFS-Validator':'1'})
                try:
                    response = urllib.request.urlopen(req,timeout=10)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    content = response.read()
                    return response.status,json.loads(content) if 'application/json' in response.headers.get('Content-Type','') else content
            def complete(ident):
                for _ in range(100):
                    _, job = request('/api/runs/'+ident)
                    if job['status'] in {'complete','failed'}:
                        self.assertEqual('complete',job['status'],job['error'])
                        return job
                    time.sleep(.03)
                self.fail('Inspection timed out')
            try:
                self.assertEqual(404,request('/api/builds',{})[0])
                self.assertNotIn(b'Build merged GTFS',request('/')[1])
                _, created = request('/api/runs',{'hastus_path':str(path),'save_indexes':True})
                job = complete(created['id'])
                status, catalog = request(f"/api/runs/{job['id']}/headways?source=hastus")
                self.assertEqual(200,status)
                self.assertEqual('r19',catalog['routes'][0]['route_id'])
                status, headways = request(f"/api/runs/{job['id']}/headways?source=hastus&date=2026-10-13&route_id=r19")
                self.assertEqual(200,status)
                self.assertEqual('25:00:00',headways['departures'][0]['time'])
                self.assertEqual('t1',headways['trips'][0]['trip_id'])
                self.assertEqual(400,request('/api/cache/offload',{'name':'../source.zip'})[0])
                _, saved = request('/api/cache')
                name = next(item['name'] for item in saved['entries'] if item['name'].startswith('index-'))
                status, offloaded = request('/api/cache/offload',{'name':name})
                self.assertEqual(200,status)
                self.assertFalse(offloaded['cleanup']['skipped'])
                self.assertFalse(offloaded['entries'])
                self.assertEqual(original,path.read_bytes())
                _, created = request('/api/runs',{'hastus_path':str(path),'save_indexes':True})
                restored = complete(created['id'])
                self.assertIn('Saved audit',restored['audit_cache_status'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                JOBS.pop(created['id'],None)
                clear_indexes()


if __name__ == '__main__':
    unittest.main()
