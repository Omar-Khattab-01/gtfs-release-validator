from __future__ import annotations

import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from gtfs_validator.details import build_detail
from gtfs_validator.engine import validate_feed
from gtfs_validator.merge import validate_exports, validate_merge


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


def write_feed(path: Path, *, mode: int = 0o644, extra: dict[str, str] | None = None) -> None:
    files = dict(FILES)
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

    def test_source_stop_disagreement_is_generic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cad_path = Path(temp_dir) / "cad.zip"
            hastus_path = Path(temp_dir) / "hastus.zip"
            final_path = Path(temp_dir) / "final.zip"
            cad_stops = "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,parent_station,wheelchair_boarding\n10017,EB935,ST-LAURENT D,45.422,-75.638,0,,0\n20000,PX100,PARLIAMENT A,45.423,-75.700,0,,0\n"
            hastus_stops = "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,parent_station,wheelchair_boarding\nEB935,3025,ST-LAURENT A,45.422,-75.638,0,,0\nPX100,3000,PARLIAMENT A,45.423,-75.700,0,,0\n"
            final_stops = "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,parent_station,wheelchair_boarding\n10017,3025,ST-LAURENT D,45.422,-75.638,0,,0\n20000,3000,PARLIAMENT A,45.423,-75.700,0,,0\n"
            write_feed(cad_path, extra={"stops.txt": cad_stops})
            write_feed(hastus_path, extra={"stops.txt": hastus_stops})
            write_feed(final_path, extra={"stops.txt": final_stops})
            report = validate_merge(cad_path, hastus_path, final_path)
            findings = [item for item in report.findings if item.rule_id == "STP005"]
            self.assertEqual(1, len(findings))
            self.assertIn("ST-LAURENT D", findings[0].observed or "")
            self.assertIn("ST-LAURENT A", findings[0].observed or "")
            self.assertEqual("10017 ↔ EB935", findings[0].key)

    def test_final_feed_is_optional_for_source_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cad_path = Path(temp_dir) / "cad.zip"
            hastus_path = Path(temp_dir) / "hastus.zip"
            cad_stops = "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,parent_station,wheelchair_boarding\n10017,EB935,ST-LAURENT D,45.422,-75.638,0,,0\n20000,PX100,PARLIAMENT A,45.423,-75.700,0,,0\n"
            hastus_stops = "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,parent_station,wheelchair_boarding\nEB935,3025,ST-LAURENT A,45.422,-75.638,0,,0\nPX100,3000,PARLIAMENT A,45.423,-75.700,0,,0\n"
            write_feed(cad_path, extra={"stops.txt": cad_stops})
            write_feed(hastus_path, extra={"stops.txt": hastus_stops})
            report = validate_exports(cad_path, hastus_path)
            self.assertEqual("oc-transpo-source-preflight", report.profile)
            self.assertEqual(2, len(report.stats["inputs"]))
            self.assertTrue(any(item.rule_id == "STP005" for item in report.findings))
            self.assertFalse(any(item.rule_id.startswith("PKG") for item in report.findings))

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

    def test_final_trip_schedule_is_compared_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cad_path = Path(temp_dir) / "cad.zip"
            hastus_path = Path(temp_dir) / "hastus.zip"
            final_path = Path(temp_dir) / "final.zip"
            write_feed(cad_path)
            write_feed(hastus_path)
            changed = FILES["stop_times.txt"].replace("25:15:00,25:15:00", "25:16:00,25:16:00")
            write_feed(final_path, extra={"stop_times.txt": changed})
            report = validate_merge(cad_path, hastus_path, final_path)
            self.assertTrue(any(item.rule_id == "TRP101" for item in report.findings))

    def test_stop_finding_opens_source_records_and_map_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cad_path = Path(temp_dir) / "cad.zip"
            hastus_path = Path(temp_dir) / "hastus.zip"
            cad_stops = "stop_id,stop_code,stop_name,stop_lat,stop_lon\n10017,EB935,ST-LAURENT D,45.422,-75.638\n"
            hastus_stops = "stop_id,stop_code,stop_name,stop_lat,stop_lon\nEB935,3025,ST-LAURENT A,45.423,-75.639\n"
            write_feed(cad_path, extra={"stops.txt": cad_stops})
            write_feed(hastus_path, extra={"stops.txt": hastus_stops})
            report = validate_exports(cad_path, hastus_path)
            finding = next(item.to_dict() for item in report.findings if item.rule_id == "STP005")
            detail = build_detail(finding, str(cad_path), str(hastus_path))
            self.assertEqual("stop", detail["type"])
            self.assertEqual("10017", detail["clevercad"]["stop_id"])
            self.assertEqual("EB935", detail["hastus"]["stop_id"])
            self.assertGreater(detail["distance_m"], 0)

    def test_trip_finding_opens_side_by_side_stop_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cad_path = Path(temp_dir) / "cad.zip"
            hastus_path = Path(temp_dir) / "hastus.zip"
            cad_stops = "stop_id,stop_code,stop_name,stop_lat,stop_lon\n10017,EB935,ST-LAURENT D,45.422,-75.638\n20000,PX100,PARLIAMENT A,45.423,-75.700\n"
            hastus_stops = "stop_id,stop_code,stop_name,stop_lat,stop_lon\nEB935,3025,ST-LAURENT D,45.422,-75.638\nPX100,3000,PARLIAMENT A,45.423,-75.700\n"
            hastus_times = FILES["stop_times.txt"].replace("10017,1", "PX100,1").replace("20000,2", "EB935,2")
            write_feed(cad_path, extra={"stops.txt": cad_stops})
            write_feed(hastus_path, extra={"stops.txt": hastus_stops, "stop_times.txt": hastus_times})
            report = validate_exports(cad_path, hastus_path)
            finding = next(item.to_dict() for item in report.findings if item.rule_id == "TRP102")
            detail = build_detail(finding, str(cad_path), str(hastus_path))
            self.assertEqual("trip", detail["type"])
            self.assertEqual(["CleverCAD", "HASTUS"], [side["label"] for side in detail["sides"]])
            self.assertEqual(2, len(detail["differences"]))


if __name__ == "__main__":
    unittest.main()
