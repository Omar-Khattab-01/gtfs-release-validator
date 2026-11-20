from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gtfs_validator.feed_index import FeedIndex
from gtfs_validator.headways import route_headways
from test_validator import FILES, write_feed


class HeadwayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'rail.zip'
        self.trips = 'route_id,service_id,trip_id,trip_headsign,direction_id,block_id,shape_id\n'
        self.times = 'trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n'

    def tearDown(self):
        self.temp.cleanup()

    def trip(self, ident, direction, stops, block='block', service='WKD'):
        self.trips += f'r19,{service},{ident},Destination,{direction},{block},shape19\n'
        for sequence, (stop, clock, pickup) in enumerate(stops, 1):
            self.times += f'{ident},{clock},{clock},{stop},{sequence},{pickup}\n'

    def index(self):
        write_feed(self.path, extra={'trips.txt': self.trips, 'stop_times.txt': self.times})
        return FeedIndex(str(self.path))

    def test_common_stop_direction_and_after_midnight_are_preserved(self):
        self.trip('a', '0', [('10014','24:00:00',0),('10017','24:05:00',0)], 'a')
        self.trip('b', '0', [('20000','24:02:00',0),('10017','24:15:00',0)], 'b')
        self.trip('opposite', '1', [('10014','24:01:00',0),('10017','24:10:00',0)], 'c')
        index = self.index()
        original = index.rows
        def no_frequencies(name):
            self.assertNotEqual('frequencies.txt', name)
            return original(name)
        with patch.object(index, 'rows', side_effect=no_frequencies):
            result = route_headways(index, date(2026,10,13), 'r19', 'all')
        self.assertEqual('10017', result['stop_id'])
        self.assertEqual([600], [row['headway_seconds'] for row in result['departures'] if row['headway_seconds'] is not None])
        self.assertEqual([24], sorted({row['hour'] for row in result['hourly']}))
        self.assertEqual(3, len(result['trips']))
        self.assertEqual({'a','b','c'}, {row['block_id'] for row in result['trips']})

    def test_dropoff_only_and_missing_departures_do_not_create_headways(self):
        self.trip('a','0',[('10017','23:50:00',0)],'a')
        self.trip('dropoff','0',[('10017','23:55:00',1)],'b')
        self.trip('missing','0',[('10017','',0)],'')
        self.trip('last','0',[('10017','25:10:00',0)],'c')
        result = route_headways(self.index(), date(2026,10,13), 'r19', threshold=30)
        self.assertEqual(4800, result['headways']['maximum'])
        self.assertEqual(1, result['excluded_no_pickup_calls'])
        self.assertEqual(1, result['missing_departure_times'])
        self.assertEqual(1, result['unassigned_blocks'])
        self.assertEqual(4, len(result['trips']))
        self.assertEqual(0, next(row for row in result['hourly'] if row['hour'] == 24)['departures'])
        self.assertIn('long_gap', {item['kind'] for item in result['issues']})

    def test_calendar_removals_and_one_day_additions_control_blocks_and_trips(self):
        self.trip('weekday','0',[('10017','24:00:00',0)],'shared')
        self.trip('special','0',[('10017','24:00:00',0)],'shared','SPECIAL')
        index = self.index()
        index.columns['calendar_dates.txt'] = []
        index.small_tables['calendar_dates.txt'] = [{'service_id':'WKD','date':'20261012','exception_type':'2'},
                                                    {'service_id':'SPECIAL','date':'20261012','exception_type':'1'}]
        monday = route_headways(index, date(2026,10,12), 'r19')
        tuesday = route_headways(index, date(2026,10,13), 'r19')
        self.assertEqual(['special'], [trip['trip_id'] for trip in monday['trips']])
        self.assertEqual(['weekday'], [trip['trip_id'] for trip in tuesday['trips']])
        self.assertFalse(monday['issues'])

    def test_repeated_stop_visits_and_block_overlap_have_occurrence_evidence(self):
        self.trip('loop','0',[('10017','24:00:00',0),('20000','24:05:00',0),('10017','24:10:00',0)],'shared')
        self.trip('overlap','1',[('10017','24:00:00',0),('20000','24:06:00',0)],'shared')
        result = route_headways(self.index(), date(2026,10,13), 'r19', '0', '10017')
        self.assertEqual(['1','3'], [call['sequence'] for call in result['departures']])
        self.assertEqual(600, result['headways']['median'])
        self.assertIn('block_overlap', {item['kind'] for item in result['issues']})


if __name__ == '__main__':
    unittest.main()
