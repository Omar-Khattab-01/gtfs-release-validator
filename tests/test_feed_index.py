from __future__ import annotations

import gc
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from gtfs_validator import feed_index, viewer
from gtfs_validator.details import build_detail
from gtfs_validator.web import Job, _run_job
from test_validator import FILES, write_feed


class FeedIndexTests(unittest.TestCase):
    def tearDown(self) -> None:
        feed_index.clear_indexes()

    def test_each_member_read_once_and_new_views_never_reopen_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.zip"
            write_feed(path)
            opened = []
            original = zipfile.ZipFile.open

            def recording(archive, member, *args, **kwargs):
                opened.append(member.filename if isinstance(member, zipfile.ZipInfo) else member)
                return original(archive, member, *args, **kwargs)

            with patch.object(zipfile.ZipFile, "open", recording):
                feed_index.get_index(str(path))
            self.assertEqual(sorted(FILES), sorted(opened))
            with patch.object(zipfile, "ZipFile", side_effect=AssertionError("ZIP was reopened")):
                self.assertEqual(1, len(viewer.inventory(str(path))["routes"]))
                self.assertEqual(1, len(viewer.route_detail(str(path), "r19")["variations"]))
                self.assertEqual(2, len(viewer.trip_detail(str(path), "t1")["stops"]))
                self.assertEqual(2, len(viewer.table_page(str(path), "stop_times.txt")["rows"]))
                detail = build_detail({"rule_id": "TRP103", "context": {"clevercad_trip_id": "t1", "hastus_trip_id": "t1", "final_trip_id": "t1"}}, str(path), str(path), str(path))
                self.assertEqual(["Both", "Both"], [row["final_source"] for row in detail["alignment"]])

    def test_cache_invalidates_when_source_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.zip"
            write_feed(path)
            first = feed_index.get_index(str(path))
            write_feed(path, extra={"stops.txt": FILES["stops.txt"].replace("ST-LAURENT D", "CHANGED STOP")})
            second = feed_index.get_index(str(path))
            self.assertIsNot(first, second)
            self.assertEqual("CHANGED STOP", second.stops["10017"]["stop_name"])

    def test_concurrent_requests_share_one_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.zip"
            write_feed(path)
            with patch.object(feed_index, "FeedIndex", wraps=feed_index.FeedIndex) as constructor:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(feed_index.get_index, [str(path)] * 8))
                self.assertEqual(1, constructor.call_count)
                self.assertTrue(all(result is results[0] for result in results))

    def test_raw_paging_preserves_values_and_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.zip"
            write_feed(path, extra={"extra.txt": 'id,name\n1,"  A, B  "\n2,C\n3,D\n'})
            first = viewer.table_page(str(path), "extra.txt", 0, 1)
            second = viewer.table_page(str(path), "extra.txt", 1, 1)
            self.assertEqual("  A, B  ", first["rows"][0]["name"])
            self.assertEqual("2", second["rows"][0]["id"])
            self.assertTrue(second["has_more"])
            self.assertFalse(viewer.table_page(str(path), "extra.txt", 2, 1)["has_more"])
            with self.assertRaises(ValueError):
                viewer.table_page(str(path), "../extra.txt")

    def test_large_route_batch_uses_parent_index_and_preserves_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.zip"
            write_feed(path)
            index = feed_index.get_index(str(path))
            with patch.object(index, "_query", wraps=index._query) as query:
                self.assertEqual(2, len(index.lookup("stop_times.txt", "t1")))
                self.assertIn("INDEXED BY records_parent", query.call_args.args[0])
            rows = index.lookup_many("stop_times.txt", [f"missing-{number}" for number in range(401)] + ["t1"])
            self.assertEqual(2, len(rows))
            self.assertEqual(["1", "2"], [row["stop_sequence"] for row in rows])

    def test_cache_cleanup_keeps_in_flight_reader_then_removes_temp_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.zip"
            write_feed(path)
            index = feed_index.get_index(str(path))
            database = index.database
            feed_index.clear_indexes()
            self.assertEqual(2, len(index.lookup("stop_times.txt", "t1")))
            del index
            gc.collect()
            self.assertFalse(database.exists())

    def test_index_failure_does_not_hide_validation_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.zip"
            write_feed(path)
            job = Job(id="index-failure", clevercad_path="", hastus_path="", final_path=str(path))
            with patch("gtfs_validator.web.get_index", side_effect=ValueError("Unreadable CSV")):
                _run_job(job)
            self.assertEqual("complete", job.status)
            self.assertIn("Unreadable CSV", job.report["stats"]["browse_index_errors"][0])


if __name__ == "__main__":
    unittest.main()
