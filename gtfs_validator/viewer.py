"""Read-only local feed browsing. No remote maps or services."""
from __future__ import annotations

from collections import defaultdict
from .details import _rows, _stop_index, _trip_stop_times
from .feed_index import get_index


def inventory(path: str) -> dict:
    routes = _rows(path, "routes.txt")
    trips = _rows(path, "trips.txt")
    counts = defaultdict(int)
    for trip in trips:
        counts[trip.get("route_id", "")] += 1
    files = get_index(path).files
    return {"routes": sorted([{**row, "trip_count": counts[row.get("route_id", "")]} for row in routes], key=lambda row: (not row.get("route_short_name", "").isdigit(), int(row["route_short_name"]) if row.get("route_short_name", "").isdigit() else row.get("route_short_name", ""))), "files": files}


def route_detail(path: str, route_id: str) -> dict:
    index = get_index(path)
    trips = index.lookup("trips.txt", route_id)
    times = defaultdict(list)
    for row in index.lookup_many("stop_times.txt", list({trip["trip_id"] for trip in trips})):
        times[row["trip_id"]].append(row)
    groups = defaultdict(list)
    for trip in trips:
        rows = sorted(times[trip["trip_id"]], key=lambda row: int(row.get("stop_sequence") or 0))
        trip = {**trip, "first_time": rows[0].get("departure_time", "") if rows else "", "last_time": rows[-1].get("arrival_time", "") if rows else "", "stop_count": len(rows)}
        groups[(trip.get("direction_id", ""), tuple(row.get("stop_id", "") for row in rows), trip.get("shape_id", ""))].append(trip)
    variations = [{"variation_id": f"V{index}", "direction_id": key[0], "stop_count": len(key[1]), "trip_count": len(items), "shape_ids": sorted({item.get("shape_id", "") for item in items}), "trips": sorted(items, key=lambda item: (item["first_time"], item["trip_id"]))} for index, (key, items) in enumerate(groups.items(), 1)]
    return {"route_id": route_id, "variations": variations}


def trip_detail(path: str, trip_id: str) -> dict:
    index = get_index(path)
    trips = index.lookup("trips.txt", trip_id, entity=True)
    trip = trips[0] if trips else None
    if trip is None:
        raise ValueError("Trip not found in this feed")
    stops = _trip_stop_times(path, trip_id, _stop_index(path))
    shape = []
    if "shapes.txt" in index.columns and trip.get("shape_id"):
        shape = index.lookup("shapes.txt", trip["shape_id"])
    shape.sort(key=lambda row: int(row.get("shape_pt_sequence") or 0))
    return {"trip": trip, "stops": stops, "shape": shape}


def table_page(path: str, name: str, offset: int = 0, limit: int = 100) -> dict:
    return get_index(path).page(name, max(0, offset), min(100, max(1, limit)))
