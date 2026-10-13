import tempfile
import unittest
from pathlib import Path
from gtfs_validator.input_paths import normalize_path
from gtfs_validator.sequence_diff import mismatch_positions
from gtfs_validator.details import _align_sequences
from gtfs_validator.merge import validate_exports
from test_validator import write_feed, FILES


class SequenceFilterTests(unittest.TestCase):
    def test_quoted_paths_preserve_internal_quotes_and_spaces(self):
        path = "C:\\GTFS\\Agency's exports\\Final file.zip"
        for wrapped in (path, '"'+path+'"', "'"+path+"'", '“'+path+'”', '‘'+path+'’', '  "'+path+'"  '):
            self.assertEqual(path,normalize_path(wrapped))
        self.assertEqual('',normalize_path('""'))
        self.assertEqual('',normalize_path(None))

    def test_prefix_middle_suffix_insertions_deletions_and_substitutions(self):
        original = ('a','b','c','d')
        for changed,expected in [
            (('x','b','c','d'),['first']),
            (('x','a','b','c','d'),['first']),
            (('b','c','d'),['first']),
            (('a','b','x','c','d'),['middle']),
            (('a','x','c','d'),['middle']),
            (('a','b','c'),['last']),
            (('a','b','c','x'),['last']),
            (('a','b','c','d','x'),['last']),
            (('x','b','y','d','z'),['first','middle','last']),
            (('x','y','z'),['first','middle','last']),
            (original,[]), ((),[]),
        ]:
            with self.subTest(changed=changed):
                self.assertEqual(expected,mismatch_positions(original,changed))
                self.assertEqual(expected,mismatch_positions(changed,original))

    def test_detail_alignment_does_not_mark_shifted_matching_rows_as_differences(self):
        stop = lambda value: {'canonical_stop_id':value}
        sides = [{'stops':list(map(stop,['a','b','c']))},{'stops':list(map(stop,['x','a','b','c','y']))}]
        rows = _align_sequences(sides)
        self.assertEqual(['first'],rows[0]['mismatch_positions'])
        self.assertEqual(['last'],rows[-1]['mismatch_positions'])
        self.assertTrue(all(row['status']=='match' and not row['mismatch_positions'] for row in rows[1:-1]))

    def test_positions_are_present_in_exported_variations_and_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            cad,hastus = Path(directory)/'cad.zip',Path(directory)/'hastus.zip'
            write_feed(cad)
            write_feed(hastus,extra={'stop_times.txt':FILES['stop_times.txt'].replace('10017,1','10014,1')})
            report = validate_exports(cad,hastus)
            route = report.stats['trip_reconciliation']['route_health'][0]
            self.assertEqual(['first'],route['variation_pairs'][0]['mismatch_positions'])
            findings = [finding for finding in report.findings if finding.rule_id in {'TRP102','TRP103'}]
            self.assertTrue(findings)
            self.assertTrue(all(finding.context['mismatch_positions']==['first'] for finding in findings))
