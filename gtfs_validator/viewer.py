"""Read-only local feed browsing. No remote maps or services."""
from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from .details import _rows, _stop_index, _trip_stop_times


def inventory(path: str) -> dict:
    routes = _rows(path, "routes.txt")
    trips = _rows(path, "trips.txt")
    counts = defaultdict(int)
    for trip in trips:
        counts[trip.get("route_id", "")] += 1
    with zipfile.ZipFile(path) as archive:
        files = [{"name": item.filename, "bytes": item.file_size} for item in archive.infolist() if not item.is_dir()]
    return {"routes": sorted([{**row, "trip_count": counts[row.get("route_id", "")]} for row in routes], key=lambda row: (not row.get("route_short_name", "").isdigit(), int(row["route_short_name"]) if row.get("route_short_name", "").isdigit() else row.get("route_short_name", ""))), "files": files}


def route_detail(path: str, route_id: str) -> dict:
    trips = [row for row in _rows(path, "trips.txt") if row.get("route_id") == route_id]
    by_id = {trip["trip_id"]: trip for trip in trips}
    times = defaultdict(list)
    with zipfile.ZipFile(path) as archive, archive.open("stop_times.txt") as raw:
        for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")):
            if row.get("trip_id") in by_id:
                times[row["trip_id"]].append(row)
    groups = defaultdict(list)
    for trip in trips:
        rows = sorted(times[trip["trip_id"]], key=lambda row: int(row.get("stop_sequence") or 0))
        trip = {**trip, "first_time": rows[0].get("departure_time", "") if rows else "", "last_time": rows[-1].get("arrival_time", "") if rows else "", "stop_count": len(rows)}
        groups[(trip.get("direction_id", ""), tuple(row.get("stop_id", "") for row in rows), trip.get("shape_id", ""))].append(trip)
    variations = [{"variation_id": f"V{index}", "direction_id": key[0], "stop_count": len(key[1]), "trip_count": len(items), "shape_ids": sorted({item.get("shape_id", "") for item in items}), "trips": sorted(items, key=lambda item: (item["first_time"], item["trip_id"]))} for index, (key, items) in enumerate(groups.items(), 1)]
    return {"route_id": route_id, "variations": variations}


def trip_detail(path: str, trip_id: str) -> dict:
    trip = next((row for row in _rows(path, "trips.txt") if row.get("trip_id") == trip_id), None)
    if trip is None:
        raise ValueError("Trip not found in this feed")
    stops = _trip_stop_times(path, trip_id, _stop_index(path))
    shape = []
    with zipfile.ZipFile(path) as archive:
        if "shapes.txt" in archive.namelist() and trip.get("shape_id"):
            with archive.open("shapes.txt") as raw:
                for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")):
                    if row.get("shape_id") == trip["shape_id"]:
                        shape.append(row)
    shape.sort(key=lambda row: int(row.get("shape_pt_sequence") or 0))
    return {"trip": trip, "stops": stops, "shape": shape}


def table_page(path: str, name: str, offset: int = 0, limit: int = 100) -> dict:
    with zipfile.ZipFile(path) as archive:
        if name not in archive.namelist() or not name.endswith(".txt"):
            raise ValueError("Unknown GTFS table")
        with archive.open(name) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            rows = []
            for index, row in enumerate(reader):
                if index < offset:
                    continue
                rows.append(row)
                if len(rows) > limit:
                    break
            return {"columns": reader.fieldnames or [], "rows": rows[:limit], "offset": offset, "has_more": len(rows) > limit}
