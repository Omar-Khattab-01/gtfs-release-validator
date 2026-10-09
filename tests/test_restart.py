import gc
import json
import os
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from gtfs_validator import audit_cache, feed_index, java_runtime
from gtfs_validator.web import Job, _run_job
from test_validator import write_feed, FILES


class RestartTests(unittest.TestCase):
    def tearDown(self):
        feed_index.clear_indexes()
        gc.collect()

    def make_job(self, directory, **kwargs):
        feeds = [str(Path(directory)/name) for name in ('cad.zip','hastus.zip','final.zip')]
        for path in feeds:
            if not Path(path).exists():
                write_feed(Path(path))
        return Job('restart', *feeds, save_indexes=True, **kwargs)

    def test_three_inputs_restore_saved_results_without_validation_or_zip_parsing(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GTFS_VALIDATOR_CACHE_DIR':directory}):
            first = self.make_job(directory)
            _run_job(first)
            self.assertEqual('complete',first.status)
            self.assertIn('Saved audit',first.audit_cache_status)
            feed_index.clear_indexes()
            gc.collect()
            second = self.make_job(directory)
            with patch('gtfs_validator.web.validate_merge',side_effect=AssertionError('Audit rerun')), patch('zipfile.ZipFile',side_effect=AssertionError('ZIP reparsed')):
                _run_job(second)
            self.assertEqual('complete',second.status,second.error)
            self.assertEqual(first.report,second.report)
            self.assertEqual(first.final_validation,second.final_validation)
            self.assertIn('Reused saved audit',second.audit_cache_status)
            self.assertEqual(3,len(second.index_status))
            self.assertTrue(all(item['status']=='Reused saved index' for item in second.index_status))

    def test_changed_source_does_not_restore_old_audit(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GTFS_VALIDATOR_CACHE_DIR':directory}):
            first = self.make_job(directory)
            _run_job(first)
            old = audit_cache.identity(first)
            write_feed(Path(first.hastus_path),extra={'stops.txt':FILES['stops.txt'].replace('ST-LAURENT D','CHANGED')})
            second = self.make_job(directory)
            self.assertNotEqual(old,audit_cache.identity(second))
            self.assertIsNone(audit_cache.load(audit_cache.identity(second)))
            _run_job(second)
            self.assertEqual('complete',second.status)
            self.assertNotEqual(first.report,second.report)

    def test_date_policy_and_day_changes_invalidate_results(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.make_job(directory)
            initial = audit_cache.identity(job)
            job.validation_date = '2030-01-01'
            self.assertNotEqual(initial,audit_cache.identity(job))
            job.validation_date = initial['validation_date']
            job.release_policy = False
            self.assertNotEqual(initial,audit_cache.identity(job))
            job.release_policy = True
            class Tomorrow(date):
                @classmethod
                def today(cls): return date.today()+timedelta(days=1)
            with patch('gtfs_validator.audit_cache.date',Tomorrow):
                self.assertNotEqual(initial,audit_cache.identity(job))

    def test_force_revalidate_runs_checks_and_corrupt_result_recovers(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GTFS_VALIDATOR_CACHE_DIR':directory}):
            first = self.make_job(directory)
            _run_job(first)
            second = self.make_job(directory,force_revalidate=True)
            from gtfs_validator.merge import validate_merge
            with patch('gtfs_validator.web.validate_merge',wraps=validate_merge) as check:
                _run_job(second)
                self.assertEqual(1,check.call_count)
            audit_cache.destination(audit_cache.identity(first)).write_text('corrupt',encoding='utf-8')
            self.assertIsNone(audit_cache.load(audit_cache.identity(first)))
            third = self.make_job(directory)
            _run_job(third)
            self.assertEqual('complete',third.status)
            self.assertIn('Saved audit',third.audit_cache_status)

    def test_failed_engine_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GTFS_VALIDATOR_CACHE_DIR':directory}):
            first = self.make_job(directory,run_agency=True)
            with patch('gtfs_validator.web.agency_checks',return_value={'status':'failed','message':'dependency missing'}):
                _run_job(first)
            self.assertIn('Not saved',first.audit_cache_status)
            self.assertIsNone(audit_cache.load(audit_cache.identity(first)))

    def test_eclipse_java_is_saved_and_found_without_path(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GTFS_VALIDATOR_SETTINGS_FILE':str(Path(directory)/'settings.json')}):
            root = Path(directory)/'Eclipse with spaces'
            binary = root/'plugins'/'org.eclipse.justj.openjdk.hotspot.jre.full.win32.x86_64_21.0.10'/'jre'/'bin'/'java.exe'
            binary.parent.mkdir(parents=True)
            binary.touch()
            (root/'eclipse.ini').write_text('-vm\n'+str(binary.parent.relative_to(root))+'\n-vmargs\n',encoding='utf-8')
            with patch('gtfs_validator.java_runtime.subprocess.run',return_value=subprocess.CompletedProcess([],0,stdout='openjdk version "21.0.10"')):
                selected,_ = java_runtime.save_java(str(root))
            binary = binary.resolve()
            self.assertEqual(binary,selected)
            with patch('gtfs_validator.java_runtime.shutil.which',return_value=None):
                self.assertEqual(str(binary),java_runtime.find_java())
            self.assertEqual(str(binary),json.loads(java_runtime.settings_path().read_text())['java_executable'])

    def test_old_java_rejected_and_missing_saved_runtime_explained(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GTFS_VALIDATOR_SETTINGS_FILE':str(Path(directory)/'settings.json')}):
            binary = Path(directory)/'java.exe'
            binary.touch()
            with patch('gtfs_validator.java_runtime.subprocess.run',return_value=subprocess.CompletedProcess([],0,stdout='java version "1.8.0"')):
                with self.assertRaisesRegex(ValueError,'17'):
                    java_runtime.save_java(str(binary))
            java_runtime.settings_path().write_text(json.dumps({'java_executable':str(Path(directory)/'missing.exe')}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'configure_java.bat'):
                java_runtime.find_java()
