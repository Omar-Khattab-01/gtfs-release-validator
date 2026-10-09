import gc
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from gtfs_validator import feed_index, cache_store
from gtfs_validator.engine import validate_feed
from gtfs_validator.final_checks import agency_checks, mobility_checks, offline_mobility_report, EvidenceList
from gtfs_validator.web import Job, _run_job
from test_validator import write_feed, FILES


class FinalChecksTests(unittest.TestCase):
    def tearDown(self):
        feed_index.clear_indexes()
        gc.collect()

    def test_saved_index_reopens_without_zip_parsing_and_promotes_session(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GTFS_VALIDATOR_CACHE_DIR': directory}):
            path = Path(directory) / 'feed.zip'
            write_feed(path)
            index = feed_index.get_index(str(path))
            self.assertEqual('Session only', index.cache_status)
            self.assertIs(index, feed_index.get_index(str(path), persist=True))
            self.assertEqual('Saved for future sessions', index.cache_status)
            self.assertEqual(1, len(feed_index.cache_info()['entries']))
            self.assertEqual([], feed_index.cache_info(True)['cleanup']['removed'])
            feed_index.clear_indexes()
            del index
            gc.collect()
            with patch.object(zipfile, 'ZipFile', side_effect=AssertionError('Reparsed ZIP')):
                reused = feed_index.get_index(str(path), persist=True)
            self.assertEqual('Reused saved index', reused.cache_status)
            self.assertEqual(2, len(reused.lookup('stop_times.txt', 't1')))
            feed_index.clear_indexes()
            del reused
            gc.collect()
            self.assertEqual(1, len(feed_index.cache_info(True)['cleanup']['removed']))
            self.assertTrue(path.exists())

    def test_corrupt_saved_index_rebuilt_and_changed_feed_has_new_identity(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GTFS_VALIDATOR_CACHE_DIR': directory}):
            path = Path(directory) / 'feed.zip'
            write_feed(path)
            index = feed_index.get_index(str(path), persist=True)
            database = index.database
            feed_index.clear_indexes()
            del index
            gc.collect()
            database.write_bytes(b'broken cache')
            rebuilt = feed_index.get_index(str(path), persist=True)
            self.assertEqual(3, len(rebuilt.stops))
            write_feed(path, extra={'stops.txt': FILES['stops.txt'].replace('ST-LAURENT D', 'NEW NAME')})
            changed = feed_index.get_index(str(path), persist=True)
            self.assertNotEqual(rebuilt.database, changed.database)
            self.assertEqual('NEW NAME', changed.stops['10017']['stop_name'])

    def test_cache_budget_falls_back_and_does_not_remove_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GTFS_VALIDATOR_CACHE_DIR': directory}), patch.object(cache_store, 'MAX_BYTES', 1):
            path = Path(directory) / 'feed.zip'
            write_feed(path)
            index = feed_index.get_index(str(path), persist=True)
            self.assertEqual('Session only', index.cache_status)
            self.assertIn('budget', index.cache_warning)
            feed_index.cache_info(True)
            self.assertTrue(path.exists())

    def test_permissions_dos_unspecified_and_world_writable_are_not_0600(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'feed.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                for name, content in FILES.items():
                    info = zipfile.ZipInfo(name)
                    info.create_system = 0
                    info.external_attr = 0x20
                    archive.writestr(info, content)
            report = validate_feed(path)
            self.assertFalse(any(item.rule_id == 'PKG009' for item in report.findings))
            self.assertTrue(any(item.rule_id == 'PKG018' for item in report.findings))
            write_feed(path, mode=0o666)
            self.assertFalse(any(item.rule_id in {'PKG009','PKG016'} for item in validate_feed(path).findings))
            write_feed(path, mode=0o600)
            self.assertTrue(any(item.rule_id == 'PKG009' for item in validate_feed(path).findings))

    def test_agency_adapter_runs_supplied_profile_and_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'feed.zip'
            write_feed(path)
            result = agency_checks(str(path), '2026-10-09', False)
            self.assertEqual('complete', result['status'])
            self.assertEqual(9, len(result['files']))
            self.assertGreater(result['counts']['errors'], 0)
            self.assertEqual(sum(file['counts']['errors'] for file in result['files']), result['counts']['errors'])
            self.assertTrue(result['reference'].endswith('routes_sort_order_list.csv'))

    def test_evidence_cap_preserves_total_counts(self):
        values = EvidenceList()
        for number in range(1000):
            values.append(str(number))
        self.assertEqual(250, len(values))
        self.assertEqual(1000, values.total)

    def test_three_feed_technical_section_excludes_sorted_source_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            cad, hastus, final = [Path(directory) / name for name in ('cad.zip','hastus.zip','final.zip')]
            write_feed(cad)
            write_feed(hastus, extra={'stops.txt':FILES['stops.txt'].replace('ST-LAURENT D','DIFFERENT NAME')})
            write_feed(final, extra={'agency.txt':FILES['agency.txt'].replace('America/Toronto','Invalid/Zone')})
            expected = [item.to_dict() for item in validate_feed(final).findings]
            job = Job('three',str(cad),str(hastus),str(final))
            _run_job(job)
            self.assertEqual('complete',job.status)
            self.assertEqual(expected,job.final_validation['technical']['findings'])
            self.assertGreater(len(job.report['findings']),len(expected))

    def test_missing_mobility_dependency_is_not_a_pass(self):
        with patch('gtfs_validator.final_checks.shutil.which', return_value=None):
            result, folder = mobility_checks('unused.zip', '2026-10-09')
        self.assertEqual('unavailable', result['status'])
        self.assertIsNone(folder)

    def test_mobility_invokes_local_file_no_updates_and_offline_report_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            jar = Path(directory) / 'validator.jar'
            jar.touch()
            def run(command, **kwargs):
                output = Path(command[command.index('-o')+1])
                result = {'notices':[{'code':'<script>','severity':'ERROR','totalNotices':500,'sampleNotices':[{'filename':'stops.txt','csvRowNumber':3}]}]}
                (output/'report.json').write_text(json.dumps(result),encoding='utf-8')
                return subprocess.CompletedProcess(command,0,stdout='success')
            with patch('gtfs_validator.final_checks.shutil.which',return_value='java'), patch('gtfs_validator.final_checks.subprocess.run',side_effect=run) as process:
                result,folder = mobility_checks(str(Path(directory)/'feed.zip'),'2026-10-09',str(jar))
            self.assertEqual(500,result['counts']['ERROR'])
            self.assertIn('--skip_validator_update',process.call_args.args[0])
            self.assertNotIn('https://', ' '.join(process.call_args.args[0]))
            document = offline_mobility_report(result).decode()
            self.assertIn('&lt;script&gt;',document)
            self.assertNotIn('<script>',document)
            self.assertNotIn('src=',document)
            folder.cleanup()

    def test_batched_agency_rows_keep_csv_numbers_without_duplicate_header_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'feed.zip'
            write_feed(path,extra={'shapes.txt':FILES['shapes.txt'].replace('45.423','broken')})
            original = feed_index.FeedIndex.batches
            with patch.object(feed_index.FeedIndex,'batches',lambda self,name: original(self,name,1)):
                result = agency_checks(str(path),'2026-10-09',False)
            shape = next(file for file in result['files'] if file['file']=='shapes.txt')
            self.assertEqual(2,shape['counts']['errors'])
            row = next(item for item in shape['errors'] if item['row'])
            self.assertEqual(3,row['row'])
            self.assertEqual('shape_pt_lat',row['field'])

    def test_final_job_keeps_engines_separate_and_marks_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'feed.zip'
            write_feed(path)
            job = Job('final', '', '', str(path), run_agency=True, run_mobility=True)
            with patch('gtfs_validator.web.mobility_checks', return_value=({'status':'unavailable','message':'No Java'}, None)):
                _run_job(job)
            self.assertEqual('complete', job.status)
            self.assertEqual('complete', job.final_validation['agency']['status'])
            self.assertEqual('unavailable', job.final_validation['mobility']['status'])
            self.assertEqual('complete', job.final_validation['technical']['status'])
            self.assertTrue(any(finding['rule_id'] == 'FINAL001' for finding in job.report['findings']))
