"""Agency-profile adapter and optional local MobilityData engine."""
from __future__ import annotations
import importlib.util
import html
import json
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from .feed_index import get_index
from .java_runtime import find_java

PACKAGE = Path(__file__).resolve().parent
DEFAULT_JAR = PACKAGE.parent / ".local-tools" / "gtfs-validator-cli.jar"


def offline_mobility_report(result: dict) -> bytes:
    """Self-contained report from canonical results; no CDN scripts or assets."""
    escape = lambda value: html.escape(str(value))
    groups = []
    for notice in result.get("notices", []):
        groups.append(f"<details><summary>{escape(notice.get('severity',''))} · {escape(notice.get('code',''))} · {escape(notice.get('totalNotices',0))} occurrences</summary><pre>{escape(json.dumps(notice.get('sampleNotices',[]),ensure_ascii=False,indent=2))}</pre></details>")
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Local MobilityData validation report</title>
<style>body{{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px}}details{{border:1px solid #bbb;padding:16px;margin:12px 0}}summary{{cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style>
<h1>MobilityData validation · local report</h1>
<p>Results produced by the canonical validator; offline presentation by GTFS Merge Auditor. Samples are not an exhaustive list of affected rows.</p>
<p>Status: {escape(result.get('status'))} · Validation date: {escape(result.get('validation_date'))}</p>
<pre>{escape(json.dumps(result.get('counts',{}),indent=2))}</pre>
{''.join(groups)}<details><summary>Engine metadata</summary><pre>{escape(json.dumps(result.get('metadata',{}),ensure_ascii=False,indent=2))}</pre></details></html>"""
    return document.encode("utf-8")


class EvidenceList(list):
    def __init__(self):
        super().__init__()
        self.total = 0

    def append(self, value):
        self.total += 1
        if len(self) < 250:
            super().append(value)


def agency_checks(path: str, validation_date: str, release_policy: bool = True, reference: str = "") -> dict:
    try:
        import pandas as pd
        import tzdata  # Supply IANA zones on Windows; fail explicitly if missing.
    except ImportError:
        return {"status": "unavailable", "message": "Install requirements.txt (pandas and tzdata) to run your agency checks."}
    spec = importlib.util.spec_from_file_location("agency_profile_run", PACKAGE / "agency_source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    selected_date = date.fromisoformat(validation_date)

    class RunDate(date):
        @classmethod
        def today(cls):
            return selected_date

    module.date = RunDate
    if not release_policy:
        module.validate_feed_dates = lambda *args: None
        module.validate_calendar_start_and_end_dates = lambda *args: None
    reference_path = Path(reference) if reference else PACKAGE / "routes_sort_order_list.csv"
    module.load_routes_sort_order_reference = lambda folder, result: pd.read_csv(reference_path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    module.new_result = lambda name: {"file": name, "status": "PASS", **{key: EvidenceList() for key in ("errors", "warnings", "info")}}
    validate_columns = module.validate_columns
    index = get_index(path)
    results = []
    for name in ("agency", "feed_info", "calendar", "calendar_dates", "routes", "trips", "stops", "stop_times", "shapes"):
        filename = name + ".txt"
        combined = {"file": filename, "errors": [], "warnings": [], "info": [], "counts": {"errors": 0, "warnings": 0, "info": 0}}
        if filename not in index.columns:
            combined["errors"] = [{"message": f"Agency profile requires {filename}", "row": None, "field": ""}]
            combined["counts"]["errors"] = 1
        else:
            offset = 0
            chunks = index.batches(filename) if name in {"shapes", "stop_times"} else iter([index.rows(filename)])
            seen_chunk = False
            for rows in chunks:
                seen_chunk = True
                frame = pd.DataFrame(rows, columns=index.columns[filename]).fillna("")
                frame.index = range(offset, offset + len(rows))
                def load(folder, file_name, result):
                    if offset == 0:
                        module.validate_headers(file_name, list(frame.columns), result)
                    return frame
                module.load_required_file = load
                module.validate_columns = validate_columns if offset == 0 else lambda *args, **kwargs: None
                result = getattr(module, f"validate_{name}_file")("")
                for key in ("errors", "warnings", "info"):
                    combined["counts"][key] += result[key].total
                    for message in result[key]:
                        if len(combined[key]) >= 250:
                            break
                        row = re.search(r"\brow (\d+)\b", message, re.IGNORECASE)
                        field = re.search(r"\bcolumn '([^']+)'", message, re.IGNORECASE)
                        if not field:
                            field = re.search(r"\binvalid (shape_\w+|stop_\w+):", message)
                        combined[key].append({"message": message, "row": int(row[1]) if row else None, "field": field[1] if field else "", "batch_start_row": offset + 2})
                offset += len(rows)
            if not seen_chunk or offset == 0:
                combined["errors"].append({"message": "GTFS table is empty", "row": None, "field": ""})
                combined["counts"]["errors"] += 1
        combined["status"] = "FAIL" if combined["counts"]["errors"] else "PASS WITH WARNINGS" if combined["counts"]["warnings"] else "PASS"
        results.append(combined)
    counts = {key: sum(item["counts"][key] for item in results) for key in ("errors", "warnings", "info")}
    return {"status": "complete", "validation_date": validation_date, "release_policy": release_policy,
            "reference": str(reference_path), "files": results, "counts": counts, "sample_limit_per_file": 250}


def mobility_checks(path: str, validation_date: str, jar: str = "") -> tuple[dict, tempfile.TemporaryDirectory | None]:
    try:
        java = find_java()
    except ValueError as exc:
        return {"status": "unavailable", "message": str(exc)}, None
    jar_path = Path(jar) if jar else DEFAULT_JAR
    if not java or not jar_path.is_file():
        return {"status": "unavailable", "message": "Java 17+ and a local MobilityData CLI JAR are required. Run configure_java.bat to remember your Eclipse runtime, then setup_mobilitydata.bat once."}, None
    folder = tempfile.TemporaryDirectory(prefix="gtfs-mobility-report-")
    try:
        # No URL input and no update check: never upload the feed or contact the website.
        process = subprocess.run([java, "-Xmx2g", "-jar", str(jar_path.resolve()), "-i", str(Path(path).resolve()),
                                  "-o", folder.name, "-c", "ca", "-d", validation_date, "--skip_validator_update"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=900)
        output = Path(folder.name)
        if process.returncode != 0 or not (output / "report.json").is_file():
            return {"status": "failed", "message": process.stdout[-4000:] or "MobilityData did not produce a report"}, folder
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        system_path = output / "system_errors.json"
        system = json.loads(system_path.read_text(encoding="utf-8")) if system_path.exists() else None
        if system and (not isinstance(system, dict) or any(system.values())):
            return {"status": "failed", "message": "MobilityData reported system errors", "system_errors": system}, folder
        notices = report.get("notices", [])
        counts = {key: sum(item.get("totalNotices", len(item.get("sampleNotices", []))) for item in notices if item.get("severity", "").upper() == key) for key in ("ERROR", "WARNING", "INFO")}
        return {"status": "complete", "counts": counts, "notices": notices, "validation_date": validation_date,
                "jar": jar_path.name, "metadata": {key: value for key, value in report.items() if key != "notices"}}, folder
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "message": str(exc)}, folder
