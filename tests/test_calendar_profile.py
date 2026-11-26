import tempfile
import unittest
from pathlib import Path

from gtfs_validator.final_checks import agency_checks
from gtfs_validator.feed_index import clear_indexes
from test_validator import write_feed


class CalendarProfileTests(unittest.TestCase):
    def profile(self, start, end, validation='2026-11-26', exceptions='', policy=True, extra_rows=''):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'feed.zip'
            write_feed(path, extra={
                'calendar.txt': 'service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n'
                                f'WKD,1,1,1,1,1,1,1,{start},{end}\n' + extra_rows,
                'calendar_dates.txt': 'service_id,date,exception_type\n' + exceptions,
                'feed_info.txt': 'feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date\n'
                                 f'OCT,https://www.octranspo.com,en,{start},{end}\n',
            })
            result = agency_checks(str(path), validation, policy)
            clear_indexes()
        return {file['file']: file for file in result['files']}

    def messages(self, file, kind):
        return '\n'.join(item['message'] for item in file[kind])

    def test_monday_start_warns_about_lead_time_without_fixed_release_dates(self):
        files = self.profile('20261130', '20261206', extra_rows='OTHER,0,0,0,0,0,1,0,20261205,20261205\n')
        for name in ['calendar.txt', 'feed_info.txt']:
            text = self.messages(files[name], 'warnings')
            self.assertIn('starts in 4 days', text)
            self.assertIn('7 calendar days inclusive', text)
            self.assertNotIn('Friday', text)
            self.assertNotIn('one month', text)
            self.assertEqual(0, files[name]['counts']['errors'])
        self.assertEqual(1, files['calendar.txt']['counts']['warnings'])

    def test_tomorrow_today_and_past_starts_use_the_selected_validation_date(self):
        for start, expected in [('20261127','starts tomorrow'), ('20261126','starts today'),
                                ('20261122','started 4 days ago')]:
            with self.subTest(start=start):
                file = self.profile(start, '20261206')['calendar.txt']
                self.assertIn(expected, self.messages(file, 'warnings') + self.messages(file, 'info'))
                self.assertEqual(int(start == '20261127'), file['counts']['warnings'])

    def test_effective_days_apply_removals_and_additions_and_ignore_unused_services(self):
        file = self.profile('20261130', '20261206', exceptions='WKD,20261130,2\nWKD,20261202,2\nWKD,20261208,1\n',
                            extra_rows='UNUSED,1,1,1,1,1,1,1,20260101,20261231\n')['calendar.txt']
        self.assertEqual({'first_date':'2026-12-01', 'last_date':'2026-12-08', 'service_days':6,
                          'span_days':8, 'remaining_service_days':6, 'start_offset_days':5}, file['coverage'])

    def test_expired_and_fully_removed_service_warn_without_inventing_replacements(self):
        expired = self.profile('20261101','20261122')['calendar.txt']
        self.assertIn('ended 4 days ago', self.messages(expired, 'warnings'))
        self.assertEqual(0, expired['coverage']['remaining_service_days'])
        empty = self.profile('20261126','20261126', exceptions='WKD,20261126,2\n')['calendar.txt']
        self.assertIn('No scheduled trip service remains', self.messages(empty, 'warnings'))
        self.assertEqual(0, empty['coverage']['service_days'])

    def test_invalid_and_reversed_dates_still_fail_and_summary_is_not_policy_gated(self):
        for start, end in [('20261301','20261231'), ('20261206','20261130')]:
            with self.subTest(start=start):
                files = self.profile(start, end)
                for name in ['calendar.txt','feed_info.txt']:
                    self.assertGreater(files[name]['counts']['errors'], 0)
        file = self.profile('20261130','20261206', policy=False)['calendar.txt']
        self.assertIn('starts in 4 days', self.messages(file, 'warnings'))


if __name__ == '__main__':
    unittest.main()
