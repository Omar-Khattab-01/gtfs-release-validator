from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import tempfile
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .archive import inspect_archive
from .models import ValidationReport
from .schema import ENUMS, PRIMARY_KEYS, REQUIRED_COLUMNS


TIME_PATTERN = re.compile(r"^(\d{1,3}):([0-5]\d):([0-5]\d)$")
DATE_PATTERN = re.compile(r"^\d{8}$")
HEX_PATTERN = re.compile(r"^[0-9A-Fa-f]{6}$")


def _time_seconds(value: str) -> int | None:
    match = TIME_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    hours, minutes, seconds = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _valid_date(value: str) -> bool:
    if not DATE_PATTERN.fullmatch(value.strip()):
        return False
    try:
        datetime.strptime(value.strip(), "%Y%m%d")
    except ValueError:
        return False
    return True


def _reader(
    archive: zipfile.ZipFile,
    file_name: str,
    report: ValidationReport,
) -> tuple[list[str], Iterator[tuple[int, dict[str, str]]]] | tuple[None, None]:
    try:
        raw = archive.open(file_name)
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        csv_reader = csv.reader(text)
        headers = next(csv_reader)
    except (KeyError, StopIteration):
        report.add(
            "CSV001",
            "blocker",
            "Structure",
            "GTFS file has no header row",
            "A header row is required.",
            file=file_name,
        )
        return None, None
    except UnicodeDecodeError as exc:
        report.add(
            "CSV002",
            "blocker",
            "Structure",
            "GTFS file is not valid UTF-8",
            str(exc),
            file=file_name,
        )
        return None, None

    normalized = [header.strip() for header in headers]
    blank_positions = [str(i + 1) for i, header in enumerate(normalized) if not header]
    duplicates = sorted(name for name, count in Counter(normalized).items() if count > 1)
    if blank_positions:
        report.add(
            "CSV003",
            "blocker",
            "Structure",
            "Blank column name",
            f"Blank header positions: {', '.join(blank_positions)}.",
            file=file_name,
        )
    if duplicates:
        report.add(
            "CSV004",
            "blocker",
            "Structure",
            "Duplicate column name",
            f"Duplicate columns: {', '.join(duplicates)}.",
            file=file_name,
        )
    missing = sorted(REQUIRED_COLUMNS.get(file_name, set()) - set(normalized))
    for column in missing:
        report.add(
            "CSV005",
            "blocker",
            "Structure",
            "Required column is missing",
            f"{file_name} requires column {column!r}.",
            file=file_name,
            expected=column,
        )

    def rows() -> Iterator[tuple[int, dict[str, str]]]:
        try:
            for row_number, values in enumerate(csv_reader, start=2):
                if len(values) != len(normalized):
                    report.add(
                        "CSV006",
                        "error",
                        "Structure",
                        "Row has the wrong number of fields",
                        f"Found {len(values)} fields; expected {len(normalized)}.",
                        file=file_name,
                        row=row_number,
                        observed=str(len(values)),
                        expected=str(len(normalized)),
                    )
                    if len(values) < len(normalized):
                        values += [""] * (len(normalized) - len(values))
                    else:
                        values = values[: len(normalized)]
                yield row_number, dict(zip(normalized, values))
        except UnicodeDecodeError as exc:
            report.add(
                "CSV002",
                "blocker",
                "Structure",
                "GTFS file is not valid UTF-8",
                str(exc),
                file=file_name,
            )
        finally:
            text.close()

    return normalized, rows()


def _check_enums(file_name: str, row_number: int, row: dict[str, str], report: ValidationReport) -> None:
    for column, allowed in ENUMS.get(file_name, {}).items():
        if column not in row:
            continue
        value = row[column].strip()
        if value not in allowed:
            report.add(
                "VAL001",
                "error",
                "Field values",
                "Invalid enumerated value",
                f"{column} has value {value!r}.",
                file=file_name,
                row=row_number,
                observed=value,
                expected=", ".join(sorted(allowed)),
            )


def _load_table(
    archive: zipfile.ZipFile,
    file_name: str,
    report: ValidationReport,
) -> tuple[list[str], list[dict[str, str]]]:
    if file_name not in archive.namelist():
        return [], []
    headers, iterator = _reader(archive, file_name, report)
    if headers is None or iterator is None:
        return [], []
    rows: list[dict[str, str]] = []
    seen_keys: dict[tuple[str, ...], int] = {}
    key_columns = PRIMARY_KEYS.get(file_name)
    for row_number, row in iterator:
        _check_enums(file_name, row_number, row, report)
        if key_columns and all(column in row for column in key_columns):
            key = tuple(row[column].strip() for column in key_columns)
            if any(not value for value in key):
                report.add(
                    "REL001",
                    "error",
                    "Relationships",
                    "Primary key is blank",
                    f"Key columns: {', '.join(key_columns)}.",
                    file=file_name,
                    row=row_number,
                )
            elif key in seen_keys:
                report.add(
                    "REL002",
                    "error",
                    "Relationships",
                    "Duplicate primary key",
                    f"Key {key!r} first appeared on row {seen_keys[key]}.",
                    file=file_name,
                    row=row_number,
                    key=" | ".join(key),
                )
            else:
                seen_keys[key] = row_number
        rows.append(row)
    report.files.setdefault(file_name, {})["rows"] = len(rows)
    if not rows:
        report.add(
            "CSV007",
            "blocker",
            "Structure",
            "GTFS file has no data rows",
            "The file contains a header but no records.",
            file=file_name,
        )
    return headers, rows


def _check_dates(file_name: str, rows: list[dict[str, str]], report: ValidationReport) -> None:
    columns = ("feed_start_date", "feed_end_date") if file_name == "feed_info.txt" else ("start_date", "end_date")
    if file_name == "calendar_dates.txt":
        columns = ("date",)
    for row_number, row in enumerate(rows, start=2):
        for column in columns:
            value = row.get(column, "").strip()
            if value and not _valid_date(value):
                report.add(
                    "VAL002",
                    "error",
                    "Field values",
                    "Invalid GTFS date",
                    f"{column} must be a real date in YYYYMMDD format.",
                    file=file_name,
                    row=row_number,
                    observed=value,
                    expected="YYYYMMDD",
                )


def _check_stops(
    rows: list[dict[str, str]],
    stop_ids: set[str],
    stop_types: dict[str, str],
    report: ValidationReport,
) -> None:
    for row_number, row in enumerate(rows, start=2):
        stop_id = row.get("stop_id", "").strip()
        location_type = row.get("location_type", "").strip()
        for column, low, high in (("stop_lat", -90, 90), ("stop_lon", -180, 180)):
            value = row.get(column, "").strip()
            if not value:
                continue
            try:
                number = float(value)
            except ValueError:
                number = low - 1
            if not low <= number <= high:
                report.add(
                    "VAL003",
                    "error",
                    "Geography",
                    "Invalid stop coordinate",
                    f"{column} is not a valid coordinate.",
                    file="stops.txt",
                    row=row_number,
                    key=stop_id,
                    observed=value,
                )
        parent = row.get("parent_station", "").strip()
        if parent and parent not in stop_ids:
            report.add(
                "REL003",
                "error",
                "Relationships",
                "Parent station does not exist",
                f"parent_station {parent!r} is not present in stops.txt.",
                file="stops.txt",
                row=row_number,
                key=stop_id,
                observed=parent,
            )
        elif parent and stop_types.get(parent) != "1":
            report.add(
                "REL011",
                "error",
                "Relationships",
                "Parent station has the wrong location type",
                f"parent_station {parent!r} must reference a location_type=1 station.",
                file="stops.txt",
                row=row_number,
                key=stop_id,
                observed=stop_types.get(parent, ""),
                expected="1",
            )
        if location_type == "1" and parent:
            report.add(
                "REL004",
                "error",
                "Relationships",
                "Station has a parent station",
                "A location_type=1 station must not reference parent_station.",
                file="stops.txt",
                row=row_number,
                key=stop_id,
            )


def _check_routes(rows: list[dict[str, str]], report: ValidationReport) -> None:
    for row_number, row in enumerate(rows, start=2):
        for column in ("route_color", "route_text_color"):
            value = row.get(column, "").strip()
            if value and not HEX_PATTERN.fullmatch(value):
                report.add(
                    "VAL004",
                    "error",
                    "Field values",
                    "Invalid route colour",
                    f"{column} must contain six hexadecimal characters without #.",
                    file="routes.txt",
                    row=row_number,
                    key=row.get("route_id", "").strip(),
                    observed=value,
                    expected="RRGGBB",
                )


def _load_shapes(archive: zipfile.ZipFile, report: ValidationReport) -> set[str]:
    """Stream the large shapes table without retaining every coordinate row."""
    file_name = "shapes.txt"
    if file_name not in archive.namelist():
        return set()
    headers, iterator = _reader(archive, file_name, report)
    if headers is None or iterator is None:
        return set()
    shape_ids: set[str] = set()
    seen_keys: set[tuple[str, int]] = set()
    row_count = 0
    for row_number, row in iterator:
        row_count += 1
        shape_id = row.get("shape_id", "").strip()
        sequence_text = row.get("shape_pt_sequence", "").strip()
        try:
            sequence = int(sequence_text)
            if sequence < 0:
                raise ValueError
        except ValueError:
            report.add(
                "GEO001",
                "error",
                "Geography",
                "Invalid shape point sequence",
                "shape_pt_sequence must be a non-negative integer.",
                file=file_name,
                row=row_number,
                key=shape_id,
                observed=sequence_text,
            )
            continue
        key = (shape_id, sequence)
        if key in seen_keys:
            report.add(
                "REL002",
                "error",
                "Relationships",
                "Duplicate primary key",
                f"Shape {shape_id!r} contains point sequence {sequence} more than once.",
                file=file_name,
                row=row_number,
                key=f"{shape_id} | {sequence}",
            )
        else:
            seen_keys.add(key)
        shape_ids.add(shape_id)
        for column, low, high in (("shape_pt_lat", -90, 90), ("shape_pt_lon", -180, 180)):
            value = row.get(column, "").strip()
            try:
                number = float(value)
            except ValueError:
                number = low - 1
            if not low <= number <= high:
                report.add(
                    "GEO002",
                    "error",
                    "Geography",
                    "Invalid shape coordinate",
                    f"{column} is not a valid coordinate.",
                    file=file_name,
                    row=row_number,
                    key=f"{shape_id}:{sequence}",
                    observed=value,
                )
    report.files.setdefault(file_name, {})["rows"] = row_count
    if not row_count:
        report.add(
            "CSV007",
            "blocker",
            "Structure",
            "GTFS file has no data rows",
            "The file contains a header but no records.",
            file=file_name,
        )
    return shape_ids


def _process_stop_times(
    archive: zipfile.ZipFile,
    report: ValidationReport,
    trip_ids: set[str],
    stop_ids: set[str],
) -> None:
    file_name = "stop_times.txt"
    if file_name not in archive.namelist():
        return
    headers, iterator = _reader(archive, file_name, report)
    if headers is None or iterator is None:
        return
    required_for_checks = {"trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"}
    if not required_for_checks <= set(headers):
        return

    row_count = 0
    with tempfile.TemporaryDirectory(prefix="gtfs-validator-db-") as temp_dir:
        connection = sqlite3.connect(str(Path(temp_dir) / "stop_times.sqlite3"))
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            "CREATE TABLE stop_times (trip_id TEXT NOT NULL, seq INTEGER NOT NULL, row_no INTEGER NOT NULL, arrival INTEGER, departure INTEGER, stop_id TEXT NOT NULL, PRIMARY KEY (trip_id, seq)) WITHOUT ROWID"
        )
        connection.execute("BEGIN")
        for row_number, row in iterator:
            row_count += 1
            _check_enums(file_name, row_number, row, report)
            trip_id = row["trip_id"].strip()
            stop_id = row["stop_id"].strip()
            seq_text = row["stop_sequence"].strip()
            arrival_text = row["arrival_time"].strip()
            departure_text = row["departure_time"].strip()

            if trip_id not in trip_ids:
                report.add(
                    "REL005",
                    "error",
                    "Relationships",
                    "Stop time references an unknown trip",
                    f"trip_id {trip_id!r} is not present in trips.txt.",
                    file=file_name,
                    row=row_number,
                    key=trip_id,
                )
            if stop_id not in stop_ids:
                report.add(
                    "REL006",
                    "error",
                    "Relationships",
                    "Stop time references an unknown stop",
                    f"stop_id {stop_id!r} is not present in stops.txt.",
                    file=file_name,
                    row=row_number,
                    key=f"{trip_id}:{seq_text}",
                )

            try:
                sequence = int(seq_text)
                if sequence < 0:
                    raise ValueError
            except ValueError:
                report.add(
                    "TIME001",
                    "error",
                    "Stop times",
                    "Invalid stop sequence",
                    "stop_sequence must be a non-negative integer.",
                    file=file_name,
                    row=row_number,
                    key=trip_id,
                    observed=seq_text,
                )
                continue

            arrival = _time_seconds(arrival_text) if arrival_text else None
            departure = _time_seconds(departure_text) if departure_text else None
            for column, text_value, parsed in (
                ("arrival_time", arrival_text, arrival),
                ("departure_time", departure_text, departure),
            ):
                if text_value and parsed is None:
                    report.add(
                        "TIME002",
                        "error",
                        "Stop times",
                        "Invalid GTFS time",
                        f"{column} must use H+:MM:SS; hours after 24 are permitted.",
                        file=file_name,
                        row=row_number,
                        key=f"{trip_id}:{sequence}",
                        observed=text_value,
                    )
            if arrival is not None and departure is not None and arrival > departure:
                report.add(
                    "TIME003",
                    "error",
                    "Stop times",
                    "Arrival is after departure",
                    "The vehicle cannot depart this stop before its arrival time.",
                    file=file_name,
                    row=row_number,
                    key=f"{trip_id}:{sequence}",
                    observed=f"{arrival_text} → {departure_text}",
                )
            try:
                connection.execute(
                    "INSERT INTO stop_times VALUES (?, ?, ?, ?, ?, ?)",
                    (trip_id, sequence, row_number, arrival, departure, stop_id),
                )
            except sqlite3.IntegrityError:
                report.add(
                    "TIME004",
                    "error",
                    "Stop times",
                    "Duplicate stop sequence within trip",
                    f"Trip {trip_id!r} contains stop_sequence {sequence} more than once.",
                    file=file_name,
                    row=row_number,
                    key=f"{trip_id}:{sequence}",
                )
        connection.commit()

        previous_trip = None
        previous_departure = None
        for trip_id, sequence, row_number, arrival, departure in connection.execute(
            "SELECT trip_id, seq, row_no, arrival, departure FROM stop_times ORDER BY trip_id, seq"
        ):
            if trip_id != previous_trip:
                previous_trip = trip_id
                previous_departure = None
            current_time = arrival if arrival is not None else departure
            if previous_departure is not None and current_time is not None and current_time < previous_departure:
                report.add(
                    "TIME005",
                    "error",
                    "Stop times",
                    "Trip times move backwards",
                    "A stop occurs before the preceding stop's departure.",
                    file=file_name,
                    row=row_number,
                    key=f"{trip_id}:{sequence}",
                    observed=str(current_time),
                    expected=f">= {previous_departure}",
                )
            if departure is not None:
                previous_departure = departure
            elif arrival is not None:
                previous_departure = arrival
        connection.close()

    report.files.setdefault(file_name, {})["rows"] = row_count


def validate_feed(path: str | Path, profile: str = "oc-transpo") -> ValidationReport:
    source = Path(path).expanduser().resolve()
    report = ValidationReport(source_path=str(source), profile=profile)
    if not source.exists() or not source.is_file():
        report.add(
            "RUN001",
            "blocker",
            "Run setup",
            "Candidate file does not exist",
            "Select an existing GTFS ZIP on this computer.",
            observed=str(source),
        )
        report.finish()
        return report

    archive = inspect_archive(source, report)
    if archive is None:
        report.finish()
        return report
    try:
        tables: dict[str, list[dict[str, str]]] = {}
        for file_name in (
            "agency.txt",
            "feed_info.txt",
            "routes.txt",
            "stops.txt",
            "trips.txt",
            "calendar.txt",
            "calendar_dates.txt",
        ):
            _, rows = _load_table(archive, file_name, report)
            tables[file_name] = rows

        for dated_file in ("feed_info.txt", "calendar.txt", "calendar_dates.txt"):
            _check_dates(dated_file, tables[dated_file], report)

        route_rows = tables["routes.txt"]
        stop_rows = tables["stops.txt"]
        trip_rows = tables["trips.txt"]
        calendar_rows = tables["calendar.txt"]
        calendar_date_rows = tables["calendar_dates.txt"]
        shape_ids = _load_shapes(archive, report)

        route_ids = {row.get("route_id", "").strip() for row in route_rows}
        stop_ids = {row.get("stop_id", "").strip() for row in stop_rows}
        stop_types = {
            row.get("stop_id", "").strip(): row.get("location_type", "").strip() or "0"
            for row in stop_rows
        }
        trip_ids = {row.get("trip_id", "").strip() for row in trip_rows}
        service_ids = {row.get("service_id", "").strip() for row in calendar_rows + calendar_date_rows}
        _check_routes(route_rows, report)
        _check_stops(stop_rows, stop_ids, stop_types, report)

        for row_number, row in enumerate(trip_rows, start=2):
            trip_id = row.get("trip_id", "").strip()
            route_id = row.get("route_id", "").strip()
            service_id = row.get("service_id", "").strip()
            shape_id = row.get("shape_id", "").strip()
            if route_id not in route_ids:
                report.add(
                    "REL007",
                    "error",
                    "Relationships",
                    "Trip references an unknown route",
                    f"route_id {route_id!r} is not present in routes.txt.",
                    file="trips.txt",
                    row=row_number,
                    key=trip_id,
                )
            if service_id not in service_ids:
                report.add(
                    "REL008",
                    "error",
                    "Relationships",
                    "Trip references an unknown service",
                    f"service_id {service_id!r} is not present in calendar files.",
                    file="trips.txt",
                    row=row_number,
                    key=trip_id,
                )
            if shape_id and shape_id not in shape_ids:
                report.add(
                    "REL009",
                    "error",
                    "Relationships",
                    "Trip references an unknown shape",
                    f"shape_id {shape_id!r} is not present in shapes.txt.",
                    file="trips.txt",
                    row=row_number,
                    key=trip_id,
                )
        _process_stop_times(
            archive,
            report,
            trip_ids,
            stop_ids,
        )

        used_shape_ids = {row.get("shape_id", "").strip() for row in trip_rows if row.get("shape_id", "").strip()}
        for shape_id in sorted(shape_ids - used_shape_ids):
            report.add(
                "REL010",
                "warning",
                "Relationships",
                "Shape is not used by any trip",
                "Geometry alone is not evidence of scheduled service.",
                file="shapes.txt",
                key=shape_id,
            )

        report.stats.update(
            {
                "routes": len(route_ids - {""}),
                "stops": len(stop_ids - {""}),
                "trips": len(trip_ids - {""}),
                "services": len(service_ids - {""}),
                "shapes": len(shape_ids - {""}),
            }
        )
    except (OSError, zipfile.BadZipFile, csv.Error, sqlite3.Error) as exc:
        report.add(
            "RUN002",
            "blocker",
            "Run setup",
            "Validation stopped unexpectedly",
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        archive.close()
    report.finish()
    return report


def report_json(report: ValidationReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
