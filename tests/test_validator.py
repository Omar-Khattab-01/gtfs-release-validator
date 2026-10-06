from __future__ import annotations

import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from gtfs_validator.engine import validate_feed


FILES = {
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nOCT,OC Transpo,https://www.octranspo.com,America/Toronto\n",
    "feed_info.txt": "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\nOC Transpo,https://www.octranspo.com,en,20261001,20261031,S1000999\n",
    "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type,route_color,route_text_color\nr19,OCT,19,St-Laurent / Parliament,3,DA291C,FFFFFF\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station,wheelchair_boarding\n10014,ST-LAURENT A,45.421,-75.639,0,,0\n10017,ST-LAURENT D,45.422,-75.638,0,,0\n20000,PARLIAMENT A,45.423,-75.700,0,,0\n",
    "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id,wheelchair_accessible,bikes_allowed\nr19,WKD,t1,Parliament,0,shape19,1,1\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type,timepoint\nt1,25:00:00,25:00:00,10017,1,0,0,1\nt1,25:15:00,25:15:00,20000,2,0,0,1\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nWKD,1,1,1,1,1,0,0,20261001,20261031\n",
    "calendar_dates.txt": "service_id,date,exception_type\nWKD,20261012,2\n",
    "shapes.txt": "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\nshape19,45.421,-75.639,1\nshape19,45.423,-75.700,2\n",
}


def write_feed(path: Path, *, mode: int = 0o644, first_stop: str = "10017", extra: dict[str, str] | None = None) -> None:
    files = dict(FILES)
    files["stop_times.txt"] = files["stop_times.txt"].replace("10017,1", f"{first_stop},1")
    if extra:
        files.update(extra)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, content.encode("utf-8"))


class ValidatorTests(unittest.TestCase):
    def test_valid_minimal_feed_has_no_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "valid.zip"
            write_feed(path)
            report = validate_feed(path)
            self.assertEqual("ELIGIBLE FOR APPROVAL", report.decision)
            self.assertEqual({"blocker": 0, "error": 0, "warning": 0, "info": 0}, report.counts)
            self.assertEqual(2, report.files["stop_times.txt"]["rows"])

    def test_owner_only_permissions_block_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad-mode.zip"
            write_feed(path, mode=0o600)
            report = validate_feed(path)
            self.assertEqual("BLOCKED", report.decision)
            self.assertTrue(any(item.rule_id == "PKG009" for item in report.findings))

    def test_route_19_wrong_first_stop_is_targeted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "route19.zip"
            write_feed(path, first_stop="10014")
            report = validate_feed(path)
            findings = [item for item in report.findings if item.rule_id == "OCT001"]
            self.assertEqual(1, len(findings))
            self.assertEqual("10014", findings[0].observed)
            self.assertEqual("10017", findings[0].expected)
            self.assertEqual("t1", findings[0].key)

    def test_nested_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nested.zip"
            write_feed(path, extra={"folder/readme.txt": "not allowed\n"})
            report = validate_feed(path)
            self.assertTrue(any(item.rule_id == "PKG003" for item in report.findings))

    def test_time_regression_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "time.zip"
            bad_times = FILES["stop_times.txt"].replace("25:15:00,25:15:00", "24:59:00,24:59:00")
            write_feed(path, extra={"stop_times.txt": bad_times})
            report = validate_feed(path)
            self.assertTrue(any(item.rule_id == "TIME005" for item in report.findings))


if __name__ == "__main__":
    unittest.main()
