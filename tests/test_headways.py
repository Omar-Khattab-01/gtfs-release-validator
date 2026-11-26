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

    def rail_index(self, line='1', parents=True):
        names = {'tw': "TUNNEY'S PASTURE O-TRAIN EAST / EST", 'ta': "TUNNEY'S PASTURE O-TRAIN",
                 'be': 'BLAIR O-TRAIN EAST / EST', 'bw': 'BLAIR O-TRAIN WEST / OUEST',
                 'trim': 'TRIM O-TRAIN WEST / OUEST', 'middle': 'RIDEAU O-TRAIN',
                 'bay': 'BAYVIEW O-TRAIN SOUTH / SUD', 'lime': 'LIMEBANK O-TRAIN NORTH / NORD',
                 'south': 'SOUTH KEYS O-TRAIN SOUTH / SUD', 'airport': 'AIRPORT O-TRAIN NORTH / AÉROPORT O-TRAIN NORD'}
        parent_ids = {'tw':'tunney', 'ta':'tunney', 'be':'blair', 'bw':'blair'} if parents else {}
        stops = 'stop_id,stop_name,parent_station,location_type\n'
        stops += ''.join(f'{sid},{name},{parent_ids.get(sid, "")},0\n' for sid, name in names.items()
                         if sid != 'trim' or 'trim' in self.times)
        if parents:
            stops += "tunney,TUNNEY'S PASTURE,,1\nblair,BLAIR,,1\n"
        routes = FILES['routes.txt'].splitlines()[0] + f'\nr19,OCT,{line},Rail line {line},1,DA291C,FFFFFF\n'
        write_feed(self.path, extra={'routes.txt':routes, 'stops.txt':stops,
                                    'trips.txt':self.trips, 'stop_times.txt':self.times})
        return FeedIndex(str(self.path))

    def rail_trips(self):
        for number, minute in enumerate([0, 10]):
            self.trip(f'e{number}','0',[('tw',f'05:{minute:02}:00',0),('be',f'05:{minute+5:02}:00',1)], f'e{number}')
            self.trip(f'w{number}','1',[('bw',f'05:{minute+3:02}:00',0),('ta',f'05:{minute+8:02}:00',1)], f'w{number}')
        self.trip('short','0',[('middle','05:07:00',0),('be','05:09:00',1)], 'short')

    def test_rail_defaults_to_origins_and_keeps_short_turns_visible(self):
        self.rail_trips()
        result = route_headways(self.rail_index(), date(2026,10,13), 'r19', 'all', '@termini')
        self.assertTrue(result['terminus_mode'])
        self.assertEqual(4, len(result['departures']))
        self.assertEqual(5, len(result['trips']))
        self.assertEqual(1, result['not_at_stop'])
        self.assertEqual(2, result['headways']['count'])
        self.assertEqual(600, result['headways']['minimum'])
        self.assertEqual("Tunney's Pasture → Blair", result['direction_labels']['0'])
        self.assertEqual("Blair → Tunney's Pasture", result['direction_labels']['1'])
        self.assertNotIn('Trim', {stop['stop_name'] for stop in result['stops']})

    def test_blair_arrival_platform_or_parent_selects_boarding_direction(self):
        self.rail_trips()
        index = self.rail_index()
        for stop in ['be', 'blair', 'terminus:Blair']:
            result = route_headways(index, date(2026,10,13), 'r19', '0', stop)
            self.assertTrue(result['direction_adjusted'])
            self.assertEqual('1', result['direction'])
            self.assertEqual(['bw','bw'], [item['stop_id'] for item in result['departures']])
            self.assertEqual(600, result['headways']['median'])

    def test_terminus_platforms_without_parent_station_are_grouped(self):
        self.rail_trips()
        result = route_headways(self.rail_index(parents=False), date(2026,10,13), 'r19', '0', 'be')
        blair = next(stop for stop in result['stops'] if stop['stop_name'] == 'Blair')
        self.assertEqual(['be','bw'], blair['stop_ids'])
        self.assertEqual(2, len(result['departures']))

    def test_future_trim_only_activates_when_served_and_gaps_do_not_mix_origins(self):
        self.rail_trips()
        self.trip('trim1','1',[('trim','05:08:00',0),('ta','05:28:00',1)], 'trim1')
        self.trip('trim2','1',[('trim','05:18:00',0),('ta','05:38:00',1)], 'trim2')
        result = route_headways(self.rail_index(), date(2026,10,13), 'r19', '1')
        self.assertEqual({'Blair','Trim'}, {item['station_name'] for item in result['departures']})
        self.assertEqual(600, result['headways']['minimum'])
        self.assertEqual(2, result['headways']['count'])
        self.assertEqual({'Blair','Trim'}, {item['station_name'] for item in result['hourly']})

    def test_partial_variations_have_origin_departures_and_can_be_filtered(self):
        self.rail_trips()
        self.trip('short2','0',[('middle','05:17:00',0),('be','05:19:00',1)], 'short2')
        index = self.rail_index()
        result = route_headways(index, date(2026,10,13), 'r19', 'all')
        self.assertTrue(result['origin_mode'])
        self.assertEqual(6, len(result['departures']))
        self.assertEqual(0, result['not_at_stop'])
        short = next(item for item in result['variations'] if item['origin'] == 'RIDEAU O-TRAIN')
        self.assertEqual(2, short['trip_count'])
        filtered = route_headways(index, date(2026,10,13), 'r19', 'all', variation_id=short['variation_id'])
        self.assertEqual({'short','short2'}, {item['trip_id'] for item in filtered['trips']})
        self.assertEqual(600, filtered['headways']['median'])
        self.assertEqual({'middle'}, {item['origin_departure']['stop_id'] for item in filtered['trips']})
        self.assertEqual({short['variation_id']}, {item['variation_id'] for item in filtered['trips']})
        with self.assertRaises(ValueError):
            route_headways(index, date(2026,10,13), 'r19', variation_id='nonexistent')

    def test_lines_two_and_four_measure_their_own_termini(self):
        for line, start, end in [('2','bay','lime'), ('4','south','airport')]:
            with self.subTest(line=line):
                self.trips = self.trips.splitlines()[0] + '\n'
                self.times = self.times.splitlines()[0] + '\n'
                self.trip('out1','0',[(start,'05:00:00',0),(end,'05:20:00',1)],'out1')
                self.trip('out2','0',[(start,'05:12:00',0),(end,'05:32:00',1)],'out2')
                self.trip('back','1',[(end,'05:03:00',0),(start,'05:23:00',1)],'back')
                result = route_headways(self.rail_index(line), date(2026,10,13), 'r19', 'all')
                self.assertEqual(3, len(result['departures']))
                self.assertEqual(720, result['headways']['median'])


if __name__ == '__main__':
    unittest.main()
