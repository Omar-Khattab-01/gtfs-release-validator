from datetime import date
from pathlib import Path
import tempfile
import unittest

from gtfs_validator.feed_index import FeedIndex
from gtfs_validator.schedule import calendar_day, calendar_month, calendar_trips
from test_validator import FILES, write_feed


class ScheduleTests(unittest.TestCase):
    def test_exception_only_route_and_rail_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'feed.zip'
            write_feed(path, extra={
                'routes.txt': FILES['routes.txt'] + 'bus1,OCT,1,Replacement bus,3,,\n'
                'rail1,OCT,1,Line 1,0,,\nrail2,OCT,2,Line 2,0,,\nrail4,OCT,4,Line 4,0,,\n',
                'trips.txt': FILES['trips.txt'] + 'bus1,SPECIAL,b1,Blair,0,,1,1\n'
                'rail1,WKD,l1,Blair,0,,1,1\nrail2,SPECIAL,l2,Limebank,0,,1,1\nrail4,SPECIAL,l4,Airport,0,,1,1\n',
                'calendar_dates.txt': FILES['calendar_dates.txt'] + 'SPECIAL,20261012,1\n',
            })
            index = FeedIndex(str(path))
            day = calendar_day(index, date(2026, 10, 12), '')['groups']
            self.assertEqual(['bus1'], [route['route_id'] for route in day['bus']['routes']])
            self.assertEqual(['WKD'], day['bus']['removed'])
            self.assertEqual(['SPECIAL'], day['bus']['added'])
            self.assertEqual(0, day['line1']['trip_count'])
            self.assertEqual(2, day['lines24']['route_count'])
            month = calendar_month(index, '2026-10', '1')['days']
            self.assertEqual(1, month[11]['groups']['bus']['route_count'])
            self.assertEqual(0, month[11]['groups']['lines24']['route_count'])
            self.assertEqual(1, month[12]['groups']['line1']['route_count'])
            self.assertEqual(0, month[12]['groups']['bus']['route_count'])

    def test_trip_details_follow_service_date_and_stop_sequence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'feed.zip'
            header, first, last = FILES['stop_times.txt'].splitlines()
            write_feed(path, extra={'stop_times.txt': '\n'.join([header, last, first]) + '\n'})
            index = FeedIndex(str(path))
            self.assertEqual([], calendar_trips(index, date(2026, 10, 12), 'r19', '')['trips'])
            trip, = calendar_trips(index, date(2026, 10, 13), 'r19', 'WKD')['trips']
            self.assertEqual(('25:00:00', '25:15:00'), (trip['first_time'], trip['last_time']))
            self.assertEqual(('ST-LAURENT D', 'PARLIAMENT A'), (trip['first_stop_name'], trip['last_stop_name']))
