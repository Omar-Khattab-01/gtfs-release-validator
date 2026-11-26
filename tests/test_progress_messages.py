import tempfile
import threading
import unittest
from pathlib import Path

from gtfs_validator.feed_index import clear_indexes
from gtfs_validator.web import Job, _run_job
from test_validator import write_feed


class ProgressRecorder:
    def __init__(self, job):
        self.job = job
        self.lock = threading.Lock()
        self.messages = []

    def __enter__(self):
        self.lock.acquire()
        return self

    def __exit__(self, *args):
        self.messages.append(self.job.progress)
        self.lock.release()


class ProgressMessageTests(unittest.TestCase):
    def tearDown(self):
        clear_indexes()

    def run_inputs(self, path, *roles):
        job = Job('progress-test', '', '')
        for role in roles:
            setattr(job, role + '_path', str(path))
        recorder = ProgressRecorder(job)
        job.lock = recorder
        _run_job(job)
        self.assertEqual('complete', job.status, job.error)
        return recorder.messages

    def test_single_exports_never_claim_to_be_compared(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'feed.zip'
            write_feed(path)
            for role in ['final', 'clevercad', 'hastus', 'rail']:
                with self.subTest(role=role):
                    messages = self.run_inputs(path, role)
                    self.assertFalse(any('compar' in message.lower() for message in messages), messages)
                    self.assertTrue(any(message.startswith('Validating ') for message in messages))

    def test_bus_and_rail_without_a_final_are_individual_inspections(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'feed.zip'
            write_feed(path)
            for source in ['clevercad', 'hastus']:
                with self.subTest(source=source):
                    messages = self.run_inputs(path, source, 'rail')
                    self.assertFalse(any('compar' in message.lower() for message in messages), messages)

    def test_actual_comparisons_name_the_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'feed.zip'
            write_feed(path)
            cases = [
                (('clevercad', 'hastus'), 'Comparing CleverCAD and HASTUS bus'),
                (('clevercad', 'final'), 'Comparing CleverCAD against final GTFS'),
                (('hastus', 'final'), 'Comparing HASTUS bus against final GTFS'),
                (('rail', 'final'), 'Comparing HASTUS rail against final GTFS'),
            ]
            for roles, message in cases:
                with self.subTest(roles=roles):
                    messages = self.run_inputs(path, *roles)
                    self.assertIn(message, messages)
                    if 'final' not in roles:
                        self.assertFalse(any('final' in item.lower() for item in messages), messages)


if __name__ == '__main__':
    unittest.main()
