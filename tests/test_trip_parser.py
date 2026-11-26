import hashlib
import tempfile
import unittest
from pathlib import Path

from gtfs_validator.merge import _load_source, _trip_summaries
from gtfs_validator.models import ValidationReport
from test_validator import write_feed, FILES


class TripParserTests(unittest.TestCase):
    def parse(self, times, trips=None):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.zip'
            extra={'stop_times.txt':times}
            if trips:extra['trips.txt']=trips
            write_feed(path,extra=extra)
            report=ValidationReport(str(path))
            feed=_load_source(path,'HASTUS',report)
            try:result=_trip_summaries(feed,{'10017':'mapped'},report)
            finally:feed.close()
        return result,report

    def test_reordered_columns_missing_optional_fields_and_blank_rows_preserve_fingerprints(self):
        rows,report=self.parse('departure_time,trip_id,stop_id,stop_sequence,arrival_time,pickup_type\n'
                               '25:15:00,t1,20000,7,25:15:00,0\n\n25:00:00,t1,10017,3,25:00:00\n')
        trip=rows['t1'][0]
        self.assertEqual(('mapped','20000'),trip.stop_sequence)
        self.assertEqual(('10017','20000'),trip.source_stop_sequence)
        self.assertEqual(hashlib.sha256(b'1|mapped\n2|20000\n').hexdigest(),trip.stop_fingerprint)
        self.assertEqual(hashlib.sha256(b'3|mapped|25:00:00|25:00:00||\n7|20000|25:15:00|25:15:00|0|\n').hexdigest(),trip.schedule_fingerprint)
        self.assertEqual('25:00:00',trip.first_time)

    def test_noncontiguous_trip_evidence_keeps_the_original_csv_record_number(self):
        trips=FILES['trips.txt']+'r19,WKD,t2,Parliament,0,shape19,1,1\n'
        rows,report=self.parse('trip_id,stop_id,stop_sequence,arrival_time,departure_time\n'
                               't1,10017,1,25:00:00,25:00:00\n\nt2,10017,1,25:00:00,25:00:00\n'
                               't1,20000,2,25:15:00,25:15:00\n',trips)
        self.assertEqual({},rows)
        finding=next(item for item in report.findings if item.rule_id=='TRP001')
        self.assertEqual(4,finding.row)


if __name__=='__main__':unittest.main()
