from __future__ import annotations

import csv
import io
import math
import zipfile
from pathlib import Path
from typing import Any


def _rows(path: str, file_name: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(Path(path)) as archive, archive.open(file_name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return [
            {str(key).strip(): (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(text)
        ]


def _stop_index(path: str) -> dict[str, dict[str, str]]:
    return {row.get("stop_id", ""): row for row in _rows(path, "stops.txt")}


def _trip_ids(path: str) -> set[str]:
    return {row.get("trip_id", "") for row in _rows(path, "trips.txt")}


def _trip_stop_times(
    path: str,
    trip_id: str,
    stop_names: dict[str, dict[str, str]],
    translation: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    started = False
    with zipfile.ZipFile(Path(path)) as archive, archive.open("stop_times.txt") as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        for row in csv.DictReader(text):
            current_trip = (row.get("trip_id") or "").strip()
            if current_trip != trip_id:
                # Both supported agency exports group stop_times by trip. Once the
                # requested block ends, avoid scanning hundreds of MB needlessly.
                if started:
                    break
                continue
            started = True
            source_stop_id = (row.get("stop_id") or "").strip()
            stop = stop_names.get(source_stop_id, {})
            result.append(
                {
                    "sequence": (row.get("stop_sequence") or "").strip(),
                    "source_stop_id": source_stop_id,
                    "canonical_stop_id": (translation or {}).get(source_stop_id, source_stop_id),
                    "stop_name": stop.get("stop_name", ""),
                    "arrival_time": (row.get("arrival_time") or "").strip(),
                    "departure_time": (row.get("departure_time") or "").strip(),
                    "pickup_type": (row.get("pickup_type") or "").strip(),
                    "drop_off_type": (row.get("drop_off_type") or "").strip(),
                }
            )
    def sequence_key(item: dict[str, Any]) -> tuple[int, str]:
        try:
            return (int(item["sequence"]), item["sequence"])
        except (TypeError, ValueError):
            return (2**31 - 1, item["sequence"])

    return sorted(result, key=sequence_key)


def _distance_m(first: dict[str, str], second: dict[str, str]) -> float | None:
    try:
        lat1, lon1 = math.radians(float(first["stop_lat"])), math.radians(float(first["stop_lon"]))
        lat2, lon2 = math.radians(float(second["stop_lat"])), math.radians(float(second["stop_lon"]))
    except (KeyError, TypeError, ValueError):
        return None
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _translation(cad_stops: dict[str, dict[str, str]], hastus_stops: dict[str, dict[str, str]]) -> dict[str, str]:
    cad_by_code: dict[str, list[str]] = {}
    for stop_id, row in cad_stops.items():
        code = row.get("stop_code", "")
        if code:
            cad_by_code.setdefault(code, []).append(stop_id)
    return {
        hastus_id: cad_by_code[hastus_id][0]
        for hastus_id in hastus_stops
        if len(cad_by_code.get(hastus_id, [])) == 1
    }


def _compare_sequences(sides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(sides) < 2:
        return []
    left = sides[0]["stops"]
    right = sides[1]["stops"]
    differences: list[dict[str, Any]] = []
    for index in range(max(len(left), len(right))):
        first = left[index] if index < len(left) else None
        second = right[index] if index < len(right) else None
        if first == second:
            continue
        fields = ("canonical_stop_id", "arrival_time", "departure_time", "pickup_type", "drop_off_type")
        changed = [field for field in fields if (first or {}).get(field) != (second or {}).get(field)]
        if changed:
            differences.append({"position": index + 1, "fields": changed})
    return differences


def build_detail(
    finding: dict[str, Any],
    clevercad_path: str,
    hastus_path: str,
    final_path: str = "",
) -> dict[str, Any]:
    context = finding.get("context") or {}
    rule_id = finding.get("rule_id", "")
    cad_stops = _stop_index(clevercad_path)
    hastus_stops = _stop_index(hastus_path)
    translation = _translation(cad_stops, hastus_stops)

    if rule_id.startswith("STP"):
        cad_id = context.get("clevercad_stop_id")
        hastus_id = context.get("hastus_stop_id")
        if not cad_id or not hastus_id:
            key = str(finding.get("key", ""))
            parts = [part.strip() for part in key.split("↔")]
            if len(parts) == 2:
                cad_id, hastus_id = parts
        cad_stop = cad_stops.get(str(cad_id), {})
        hastus_stop = hastus_stops.get(str(hastus_id), {})
        distance = _distance_m(cad_stop, hastus_stop)
        return {
            "type": "stop",
            "clevercad": cad_stop,
            "hastus": hastus_stop,
            "distance_m": round(distance, 1) if distance is not None else None,
        }

    if rule_id.startswith("TRP"):
        cad_trip_id = context.get("clevercad_trip_id")
        hastus_trip_id = context.get("hastus_trip_id")
        source_ids = context.get("source_trip_ids") or []
        cad_ids = _trip_ids(clevercad_path)
        hastus_ids = _trip_ids(hastus_path)
        if not cad_trip_id:
            cad_trip_id = next((trip_id for trip_id in source_ids if trip_id in cad_ids), None)
        if not hastus_trip_id:
            hastus_trip_id = next((trip_id for trip_id in source_ids if trip_id in hastus_ids), None)
        sides: list[dict[str, Any]] = []
        if cad_trip_id:
            sides.append(
                {
                    "label": "CleverCAD",
                    "trip_id": cad_trip_id,
                    "stops": _trip_stop_times(clevercad_path, cad_trip_id, cad_stops),
                }
            )
        if hastus_trip_id:
            sides.append(
                {
                    "label": "HASTUS",
                    "trip_id": hastus_trip_id,
                    "stops": _trip_stop_times(hastus_path, hastus_trip_id, hastus_stops, translation),
                }
            )
        final_trip_id = str(finding.get("key", "")) if final_path and rule_id in {"TRP100", "TRP101"} else ""
        if final_trip_id:
            final_stops = _stop_index(final_path)
            sides.append(
                {
                    "label": "Final merged GTFS",
                    "trip_id": final_trip_id,
                    "stops": _trip_stop_times(final_path, final_trip_id, final_stops),
                }
            )
        return {
            "type": "trip",
            "sides": sides,
            "differences": _compare_sequences(sides[:2]),
            "route_short_name": context.get("route_short_name", ""),
            "headsign": context.get("headsign", ""),
            "first_time": context.get("first_time", ""),
            "last_time": context.get("last_time", ""),
        }

    return {"type": "generic", "finding": finding}
