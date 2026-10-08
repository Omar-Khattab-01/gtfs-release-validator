from __future__ import annotations

import difflib
import math
from typing import Any
from .feed_index import get_index


def _rows(path: str, file_name: str) -> list[dict[str, str]]:
    return get_index(path).rows(file_name)


def _stop_index(path: str) -> dict[str, dict[str, str]]:
    return get_index(path).stops


def _trip_ids(path: str) -> set[str]:
    return get_index(path).trip_ids


def _trip_stop_times(
    path: str,
    trip_id: str,
    stop_names: dict[str, dict[str, str]],
    translation: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in get_index(path).lookup("stop_times.txt", trip_id):
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
                "source_record": stop,
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


def _align_sequences(sides: list[dict[str, Any]], compare_schedule: bool = False) -> list[dict[str, Any]]:
    if len(sides) < 2:
        return []
    left = sides[0]["stops"]
    right = sides[1]["stops"]
    matcher = difflib.SequenceMatcher(
        a=[row["canonical_stop_id"] for row in left],
        b=[row["canonical_stop_id"] for row in right],
        autojunk=False,
    )
    alignment: list[dict[str, Any]] = []
    schedule_fields = ("arrival_time", "departure_time", "pickup_type", "drop_off_type")

    def append(first: dict[str, Any] | None, second: dict[str, Any] | None, status: str) -> None:
        fields = [field for field in schedule_fields if compare_schedule and first and second and first.get(field) != second.get(field)]
        if status == "match" and compare_schedule and fields:
            status = "schedule_difference"
        alignment.append({"clevercad": first, "hastus": second, "status": status, "fields": fields})

    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(left_end - left_start):
                append(left[left_start + offset], right[right_start + offset], "match")
            continue
        if tag == "delete":
            for first in left[left_start:left_end]:
                append(first, None, "clevercad_only")
            continue
        if tag == "insert":
            for second in right[right_start:right_end]:
                append(None, second, "hastus_only")
            continue
        width = max(left_end - left_start, right_end - right_start)
        for offset in range(width):
            first = left[left_start + offset] if left_start + offset < left_end else None
            second = right[right_start + offset] if right_start + offset < right_end else None
            status = "different_stop" if first and second else ("clevercad_only" if first else "hastus_only")
            append(first, second, status)
    return alignment


def build_detail(
    finding: dict[str, Any],
    clevercad_path: str,
    hastus_path: str,
    final_path: str = "",
) -> dict[str, Any]:
    context = finding.get("context") or {}
    rule_id = finding.get("rule_id", "")
    cad_stops = _stop_index(clevercad_path) if clevercad_path else {}
    hastus_stops = _stop_index(hastus_path) if hastus_path else {}
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
        cad_ids = _trip_ids(clevercad_path) if clevercad_path else set()
        hastus_ids = _trip_ids(hastus_path) if hastus_path else set()
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
        final_trip_id = context.get("final_trip_id", "") or (str(finding.get("key", "")) if final_path and rule_id in {"TRP100", "TRP101"} else "")
        if final_trip_id:
            final_stops = _stop_index(final_path)
            sides.append(
                {
                    "label": "Final merged GTFS",
                    "trip_id": final_trip_id,
                    "stops": _trip_stop_times(final_path, final_trip_id, final_stops),
                }
            )
        source_sides = [side for side in sides if side["label"] != "Final merged GTFS"]
        alignment = _align_sequences(source_sides, compare_schedule=rule_id == "TRP101")
        if len(source_sides) == 1:
            source_key = "clevercad" if source_sides[0]["label"] == "CleverCAD" else "hastus"
            alignment = [{"clevercad": None, "hastus": None, source_key: stop, "status": source_key + "_only", "fields": []} for stop in source_sides[0]["stops"]]
        final_side = next((side for side in sides if side["label"] == "Final merged GTFS"), None)
        if final_side:
            # Align final stops against the union of the two source columns.
            # Prefer CAD IDs where both sources occupy a substitution row.
            base = [row.get("clevercad") or row.get("hastus") for row in alignment]
            matcher = difflib.SequenceMatcher(a=[stop["canonical_stop_id"] for stop in base], b=[stop["canonical_stop_id"] for stop in final_side["stops"]], autojunk=False)
            merged = []
            for tag, a, b, c, d in matcher.get_opcodes():
                for offset in range(max(b-a, d-c)):
                    row = dict(alignment[a+offset]) if a+offset < b else {"clevercad": None, "hastus": None, "status": "final_only", "fields": []}
                    row["final"] = final_side["stops"][c+offset] if c+offset < d else None
                    final_id = (row["final"] or {}).get("canonical_stop_id")
                    matched = [label for label, key in (("CleverCAD", "clevercad"), ("HASTUS", "hastus")) if final_id and (row.get(key) or {}).get("canonical_stop_id") == final_id]
                    row["final_source"] = "Both" if len(matched) == 2 else matched[0] if matched else "Neither" if final_id else "Absent from final"
                    merged.append(row)
            alignment = merged
        return {
            "type": "trip",
            "sides": sides,
            "alignment": alignment,
            "differences": [row for row in alignment if row["status"] != "match"],
            "final_supplied": bool(final_path),
            "route_short_name": context.get("route_short_name", ""),
            "headsign": context.get("headsign", ""),
            "first_time": context.get("first_time", ""),
            "last_time": context.get("last_time", ""),
            "clevercad_variation_id": context.get("clevercad_variation_id", ""),
            "hastus_variation_id": context.get("hastus_variation_id", ""),
            "clevercad_shape_id": context.get("clevercad_shape_id", ""),
            "hastus_shape_id": context.get("hastus_shape_id", ""),
        }

    return {"type": "generic", "finding": finding}
