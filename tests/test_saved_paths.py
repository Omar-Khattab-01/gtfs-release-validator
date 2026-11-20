import gc
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gtfs_validator import audit_cache, feed_index, source_cache
from gtfs_validator.web import Job, _run_job
from test_validator import FILES, write_feed


class SavedPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'GTFS_VALIDATOR_CACHE_DIR':str(self.root/'cache')})
        self.environment.start()
        self.feed = self.root/'source.zip'
        write_feed(self.feed)

    def tearDown(self):
        feed_index.clear_indexes()
        gc.collect()
        self.environment.stop()
        self.temp.cleanup()

    def test_restart_uses_saved_path_without_full_hash_or_index_loading(self):
        first = Job('first','',str(self.feed),save_indexes=True)
        _run_job(first)
        self.assertEqual('complete',first.status,first.error)
        feed_index.clear_indexes()
        gc.collect()
        second = Job('second','',str(self.feed),save_indexes=True)
        with patch('gtfs_validator.source_cache._hash_source',side_effect=AssertionError('Full ZIP hash repeated')), \
             patch('gtfs_validator.web.get_index',side_effect=AssertionError('Index eagerly loaded')), \
             patch('zipfile.ZipFile',side_effect=AssertionError('ZIP parsed again')):
            _run_job(second)
        self.assertEqual('complete',second.status,second.error)
        self.assertEqual(first.report,second.report)
        self.assertIn('Reused saved audit',second.audit_cache_status)
        with patch('zipfile.ZipFile',side_effect=AssertionError('ZIP parsed when browsing')):
            restored = feed_index.get_index(str(self.feed))
        self.assertEqual('Reused saved index',restored.cache_status)

    def test_changed_file_and_explicit_verification_refresh_the_fingerprint(self):
        first = source_cache.fingerprint(self.feed)
        write_feed(self.feed,extra={'stops.txt':FILES['stops.txt'].replace('ST-LAURENT D','NEW NAME')})
        second = source_cache.fingerprint(self.feed)
        self.assertNotEqual(first['sha256'],second['sha256'])
        with patch('gtfs_validator.source_cache._hash_source',wraps=source_cache._hash_source) as verify:
            source_cache.fingerprint(self.feed,verify=True)
            self.assertEqual(1,verify.call_count)
        expected = hashlib.sha256(self.feed.read_bytes()).hexdigest()
        self.assertEqual(expected,second['sha256'])

    def test_offload_releases_idle_indexes_and_associated_audits_only(self):
        original = self.feed.read_bytes()
        job = Job('saved','',str(self.feed),save_indexes=True)
        _run_job(job)
        items = feed_index.cache_info()['entries']
        index = next(item for item in items if item['name'].startswith('index-'))
        self.assertEqual([str(self.feed.resolve())],index['paths'])
        result = feed_index.offload_cache(index['name'])
        self.assertFalse(result['cleanup']['skipped'])
        self.assertFalse(result['entries'])
        self.assertEqual(original,self.feed.read_bytes())
        self.assertIsNone(audit_cache.load(audit_cache.identity(job)))

    def test_in_flight_reader_is_protected_then_can_be_offloaded(self):
        reader = feed_index.get_index(str(self.feed),persist=True)
        database = reader.database
        result = feed_index.offload_cache(database.name)
        self.assertIn(database.name,result['cleanup']['skipped'])
        self.assertEqual(2,len(reader.lookup('stop_times.txt','t1')))
        del reader
        gc.collect()
        result = feed_index.offload_cache(database.name)
        self.assertIn(database.name,result['cleanup']['removed'])
        self.assertFalse(database.exists())

    def test_offloading_all_clears_obsolete_path_records_and_keeps_other_files(self):
        source_cache.fingerprint(self.feed)
        keep = self.root/'cache'/'agency-note.txt'
        keep.write_text('keep')
        result = feed_index.offload_cache()
        self.assertFalse(source_cache.paths_by_index())
        self.assertTrue(keep.exists())
        self.assertEqual([],result['cleanup']['skipped'])
        with self.assertRaises(ValueError):
            feed_index.offload_cache('../../source.zip')


if __name__ == '__main__':
    unittest.main()
