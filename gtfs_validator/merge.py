from __future__ import annotations

import csv
import difflib
import hashlib
import io
import math
import re
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .engine import validate_feed
from .models import ValidationReport


SOURCE_REQUIRED = {"stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}


@dataclass
class SourceFeed:
    label: str
    path: Path
    archive: zipfile.ZipFile
    sha256: str
    stops: list[dict[str, str]]
    routes: list[dict[str, str]]
    trips: list[dict[str, str]]
    shape_ids: set[str]
    service_ids: set[str]
    used_stop_ids: set[str]

    def close(self) -> None:
        self.archive.close()


@dataclass(frozen=True)
class TripSummary:
    trip_id: str
    canonical_trip_id: str
    route_short_name: str
    direction_id: str
    headsign: str
    first_time: str
    last_time: str
    shape_id: str
    stop_count: int
    stop_sequence: tuple[str, ...]
    stop_fingerprint: str
    schedule_fingerprint: str

    @property
    def journey_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.route_short_name,
            self.direction_id,
            self.headsign,
            self.first_time,
            self.last_time,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_root_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(name) and not normalized.startswith("/") and len(path.parts) == 1 and path.parts[0] not in {".", ".."}


def _read_rows(archive: zipfile.ZipFile, file_name: str) -> list[dict[str, str]]:
    with archive.open(file_name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return [
            {str(key).strip(): (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(text)
        ]


def _read_ids(archive: zipfile.ZipFile, file_name: str, column: str) -> set[str]:
    if file_name not in archive.namelist():
        return set()
    with archive.open(file_name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return {(row.get(column) or "").strip() for row in csv.DictReader(text)} - {""}


def _load_source(path_value: str | Path, label: str, report: ValidationReport) -> SourceFeed | None:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        report.add(
            "MRG001",
            "blocker",
            "Merge inputs",
            f"{label} export does not exist",
            "Select an existing source ZIP on this computer.",
            observed=str(path),
        )
        return None
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        report.add(
            "MRG002",
            "blocker",
            "Merge inputs",
            f"{label} export is not a readable ZIP",
            str(exc),
            observed=str(path),
        )
        return None
    names = archive.namelist()
    unsafe = [name for name in names if not _safe_root_name(name)]
    if unsafe:
        report.add(
            "MRG003",
            "blocker",
            "Merge inputs",
            f"{label} export has unsafe or nested members",
            ", ".join(unsafe[:20]),
        )
        archive.close()
        return None
    missing = sorted(SOURCE_REQUIRED - set(names))
    if missing:
        report.add(
            "MRG004",
            "blocker",
            "Merge inputs",
            f"{label} export is missing required tables",
            ", ".join(missing),
        )
        archive.close()
        return None
    bad_member = archive.testzip()
    if bad_member:
        report.add(
            "MRG005",
            "blocker",
            "Merge inputs",
            f"{label} export failed its ZIP integrity test",
            bad_member,
        )
        archive.close()
        return None
    try:
        return SourceFeed(
            label=label,
            path=path,
            archive=archive,
            sha256=_sha256(path),
            stops=_read_rows(archive, "stops.txt"),
            routes=_read_rows(archive, "routes.txt"),
            trips=_read_rows(archive, "trips.txt"),
            shape_ids=_read_ids(archive, "shapes.txt", "shape_id"),
            service_ids=_read_ids(archive, "calendar.txt", "service_id")
            | _read_ids(archive, "calendar_dates.txt", "service_id"),
            used_stop_ids=set(),
        )
    except (KeyError, UnicodeDecodeError, csv.Error) as exc:
        report.add(
            "MRG006",
            "blocker",
            "Merge inputs",
            f"{label} export could not be parsed",
            str(exc),
        )
        archive.close()
        return None


def _index_unique(rows: list[dict[str, str]], column: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(column, "").strip()
        if value and value not in result:
            result[value] = row
    return result


def _group(rows: list[dict[str, str]], column: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        value = row.get(column, "").strip()
        if value:
            result[value].append(row)
    return dict(result)


def _normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _distance_m(a: dict[str, str], b: dict[str, str]) -> float | None:
    try:
        lat1, lon1 = math.radians(float(a["stop_lat"])), math.radians(float(a["stop_lon"]))
        lat2, lon2 = math.radians(float(b["stop_lat"])), math.radians(float(b["stop_lon"]))
    except (KeyError, TypeError, ValueError):
        return None
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _source_trip_id(row: dict[str, str]) -> str:
    trip_id = row.get("trip_id", "").strip()
    service_id = row.get("service_id", "").strip()
    suffix = f"-{service_id}"
    if service_id and trip_id.endswith(suffix):
        return trip_id[: -len(suffix)]
    return trip_id


def _trip_summaries(
    feed: SourceFeed,
    stop_translate: dict[str, str],
    report: ValidationReport,
) -> dict[str, list[TripSummary]]:
    trip_meta = {row.get("trip_id", ""): row for row in feed.trips}
    route_names = {
        row.get("route_id", ""): row.get("route_short_name", "")
        for row in feed.routes
    }
    summaries: dict[str, list[TripSummary]] = defaultdict(list)
    closed: set[str] = set()
    current_id: str | None = None
    current_rows: list[tuple[int, str, str, str, str, str]] = []

    def finish() -> bool:
        nonlocal current_id, current_rows
        if current_id is None:
            return True
        meta = trip_meta.get(current_id)
        if meta is None:
            current_rows = []
            return True
        current_rows.sort(key=lambda item: item[0])
        stops_digest = hashlib.sha256()
        schedule_digest = hashlib.sha256()
        for position, (sequence, stop_id, arrival, departure, pickup, dropoff) in enumerate(current_rows, start=1):
            # A variation is the ordered translated stop pattern. Source exports
            # may number the same sequence differently, so use list position.
            stops_digest.update(f"{position}|{stop_id}\n".encode())
            schedule_digest.update(
                f"{sequence}|{stop_id}|{arrival}|{departure}|{pickup}|{dropoff}\n".encode()
            )
        first = current_rows[0]
        last = current_rows[-1]
        canonical = _source_trip_id(meta)
        summary = TripSummary(
            trip_id=current_id,
            canonical_trip_id=canonical,
            route_short_name=route_names.get(meta.get("route_id", ""), ""),
            direction_id=meta.get("direction_id", ""),
            headsign=_normalize_name(meta.get("trip_headsign", "")),
            first_time=first[3] or first[2],
            last_time=last[2] or last[3],
            shape_id=meta.get("shape_id", ""),
            stop_count=len(current_rows),
            stop_sequence=tuple(row[1] for row in current_rows),
            stop_fingerprint=stops_digest.hexdigest(),
            schedule_fingerprint=schedule_digest.hexdigest(),
        )
        summaries[canonical].append(summary)
        closed.add(current_id)
        current_rows = []
        return True

    try:
        with feed.archive.open("stop_times.txt") as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            for row_number, row in enumerate(csv.DictReader(text), start=2):
                trip_id = (row.get("trip_id") or "").strip()
                if trip_id != current_id:
                    finish()
                    if trip_id in closed:
                        report.add(
                            "TRP001",
                            "error",
                            "Trip reconciliation",
                            f"{feed.label} stop_times is not grouped by trip",
                            "Trip comparison requires each trip's stop-time rows to be contiguous. Re-export or sort by trip_id and stop_sequence.",
                            file=f"{feed.label}:stop_times.txt",
                            row=row_number,
                            key=trip_id,
                        )
                        return {}
                    current_id = trip_id
                stop_id = (row.get("stop_id") or "").strip()
                feed.used_stop_ids.add(stop_id)
                translated_stop = stop_translate.get(stop_id, stop_id)
                try:
                    sequence = int((row.get("stop_sequence") or "").strip())
                except ValueError:
                    continue
                current_rows.append(
                    (
                        sequence,
                        translated_stop,
                        (row.get("arrival_time") or "").strip(),
                        (row.get("departure_time") or "").strip(),
                        (row.get("pickup_type") or "").strip(),
                        (row.get("drop_off_type") or "").strip(),
                    )
                )
        finish()
    except (KeyError, UnicodeDecodeError, csv.Error) as exc:
        report.add(
            "TRP002",
            "error",
            "Trip reconciliation",
            f"{feed.label} trip patterns could not be read",
            str(exc),
            file=f"{feed.label}:stop_times.txt",
        )
        return {}
    return dict(summaries)


def _hastus_stop_translation(
    cad: SourceFeed,
    hastus: SourceFeed,
    final: SourceFeed | None = None,
) -> dict[str, str]:
    cad_by_code = _group(cad.stops, "stop_code")
    final_ids = {row.get("stop_id", "") for row in final.stops} if final else set()
    translation: dict[str, str] = {}
    for row in hastus.stops:
        hastus_id = row.get("stop_id", "")
        matches = cad_by_code.get(hastus_id, [])
        if len(matches) == 1 and (not final or matches[0].get("stop_id", "") in final_ids):
            translation[hastus_id] = matches[0]["stop_id"]
        elif final and hastus_id in final_ids:
            translation[hastus_id] = hastus_id
    return translation


def _sequence_difference_count(first: tuple[str, ...], second: tuple[str, ...]) -> int:
    matcher = difflib.SequenceMatcher(a=first, b=second, autojunk=False)
    return sum(max(left_end - left_start, right_end - right_start) for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes() if tag != "equal")


def _variation_similarity(first: dict[str, object], second: dict[str, object]) -> tuple[float, float]:
    first_sequence = tuple(first.get("_stop_sequence", ()))
    second_sequence = tuple(second.get("_stop_sequence", ()))
    sequence_ratio = difflib.SequenceMatcher(a=first_sequence, b=second_sequence, autojunk=False).ratio()
    first_headsign = " ".join(str(value) for value in first.get("headsigns", []))
    second_headsign = " ".join(str(value) for value in second.get("headsigns", []))
    headsign_ratio = difflib.SequenceMatcher(a=first_headsign, b=second_headsign, autojunk=False).ratio()
    endpoints = 0.0
    if first_sequence and second_sequence:
        endpoints = (float(first_sequence[0] == second_sequence[0]) + float(first_sequence[-1] == second_sequence[-1])) / 2
    count_ratio = min(len(first_sequence), len(second_sequence)) / max(len(first_sequence), len(second_sequence), 1)
    return sequence_ratio, 0.82 * sequence_ratio + 0.08 * endpoints + 0.06 * headsign_ratio + 0.04 * count_ratio


def _direction_alignment_quality(
    cad_variations: list[dict[str, object]],
    hastus_variations: list[dict[str, object]],
    *,
    reversed_ids: bool,
) -> tuple[int, int, float]:
    """Score a route-wide 0/1 direction convention using stop-pattern evidence."""
    candidates: list[tuple[float, str, str]] = []
    for cad_item in cad_variations:
        cad_directions = set(str(value) for value in cad_item.get("direction_ids", []))
        for hastus_item in hastus_variations:
            hastus_directions = set(str(value) for value in hastus_item.get("direction_ids", []))
            if not cad_directions or not hastus_directions:
                compatible = True
            elif reversed_ids:
                compatible = any(
                    {cad_direction, hastus_direction} == {"0", "1"}
                    for cad_direction in cad_directions
                    for hastus_direction in hastus_directions
                )
            else:
                compatible = not cad_directions.isdisjoint(hastus_directions)
            if not compatible:
                continue
            sequence_ratio, _score = _variation_similarity(cad_item, hastus_item)
            candidates.append((sequence_ratio, str(cad_item["variation_id"]), str(hastus_item["variation_id"])))

    paired_cad: set[str] = set()
    paired_hastus: set[str] = set()
    ratios: list[float] = []
    for ratio, cad_id, hastus_id in sorted(candidates, reverse=True):
        if cad_id in paired_cad or hastus_id in paired_hastus:
            continue
        paired_cad.add(cad_id)
        paired_hastus.add(hastus_id)
        ratios.append(ratio)
    return (
        sum(ratio >= 0.70 for ratio in ratios),
        sum(ratio == 1.0 for ratio in ratios),
        round(sum(ratios), 6),
    )


def _infer_direction_alignment(
    cad_variations: list[dict[str, object]],
    hastus_variations: list[dict[str, object]],
) -> str:
    directions = {
        str(value)
        for item in cad_variations + hastus_variations
        for value in item.get("direction_ids", [])
        if str(value)
    }
    if not directions or not directions.issubset({"0", "1"}):
        return "same"
    same_quality = _direction_alignment_quality(cad_variations, hastus_variations, reversed_ids=False)
    reversed_quality = _direction_alignment_quality(cad_variations, hastus_variations, reversed_ids=True)
    return "reversed" if reversed_quality > same_quality else "same"


def _directions_compatible(cad_item: dict[str, object], hastus_item: dict[str, object], alignment: str) -> bool:
    cad_directions = set(str(value) for value in cad_item.get("direction_ids", []))
    hastus_directions = set(str(value) for value in hastus_item.get("direction_ids", []))
    if not cad_directions or not hastus_directions:
        return True
    if alignment == "reversed":
        return any(
            {cad_direction, hastus_direction} == {"0", "1"}
            for cad_direction in cad_directions
            for hastus_direction in hastus_directions
        )
    return not cad_directions.isdisjoint(hastus_directions)


def _pair_route_variations(
    cad_variations: list[dict[str, object]],
    hastus_variations: list[dict[str, object]],
    journey_links: dict[tuple[str, str], int],
) -> tuple[list[dict[str, object]], str]:
    """Pair patterns independently from exact trip times and headsign text."""
    direction_alignment = _infer_direction_alignment(cad_variations, hastus_variations)
    candidates: list[tuple[float, float, int, dict[str, object], dict[str, object], str]] = []
    for cad_item in cad_variations:
        for hastus_item in hastus_variations:
            if not _directions_compatible(cad_item, hastus_item, direction_alignment):
                continue
            sequence_ratio, score = _variation_similarity(cad_item, hastus_item)
            linked_journeys = journey_links.get((str(cad_item["variation_id"]), str(hastus_item["variation_id"])), 0)
            exact = cad_item["pattern_fingerprint"] == hastus_item["pattern_fingerprint"]
            if not exact and not linked_journeys and sequence_ratio < 0.70:
                continue
            evidence = "exact stop sequence" if exact else ("matching scheduled journey" if linked_journeys else "similar stop sequence")
            if direction_alignment == "reversed":
                evidence += "; source direction IDs are reversed"
            priority = 3.0 if exact else (2.0 + min(linked_journeys, 50) / 1000 if linked_journeys else score)
            candidates.append((priority, score, linked_journeys, cad_item, hastus_item, evidence))

    candidates.sort(key=lambda item: (-item[0], -item[1], str(item[3]["variation_id"]), str(item[4]["variation_id"])))
    paired_cad: set[str] = set()
    paired_hastus: set[str] = set()
    pairs: list[dict[str, object]] = []
    for _priority, score, linked_journeys, cad_item, hastus_item, evidence in candidates:
        cad_id = str(cad_item["variation_id"])
        hastus_id = str(hastus_item["variation_id"])
        if cad_id in paired_cad or hastus_id in paired_hastus:
            continue
        first_sequence = tuple(cad_item.get("_stop_sequence", ()))
        second_sequence = tuple(hastus_item.get("_stop_sequence", ()))
        difference_count = _sequence_difference_count(first_sequence, second_sequence)
        competing = [
            candidate for candidate in candidates
            if candidate[3] is cad_item and candidate[4] is not hastus_item and candidate[3]["variation_id"] not in paired_cad and candidate[4]["variation_id"] not in paired_hastus
        ] + [
            candidate for candidate in candidates
            if candidate[4] is hastus_item and candidate[3] is not cad_item and candidate[3]["variation_id"] not in paired_cad and candidate[4]["variation_id"] not in paired_hastus
        ]
        ambiguous = difference_count > 0 and any(abs(score - candidate[1]) <= 0.015 for candidate in competing)
        status = "matching" if difference_count == 0 else ("ambiguous" if ambiguous else "issues")
        pairs.append(
            {
                "pair_id": f"{cad_id}|{hastus_id}",
                "status": status,
                "clevercad_variation_id": cad_id,
                "hastus_variation_id": hastus_id,
                "similarity_percent": round(score * 100, 1),
                "difference_count": difference_count,
                "linked_journeys": linked_journeys,
                "reason": "multiple similarly strong candidates" if ambiguous else evidence,
            }
        )
        paired_cad.add(cad_id)
        paired_hastus.add(hastus_id)

    for item in cad_variations:
        variation_id = str(item["variation_id"])
        if variation_id not in paired_cad:
            pairs.append({"pair_id": f"{variation_id}|", "status": "not_comparable", "clevercad_variation_id": variation_id, "hastus_variation_id": "", "similarity_percent": None, "difference_count": None, "linked_journeys": 0, "reason": "no sufficiently similar HASTUS pattern in the same direction"})
    for item in hastus_variations:
        variation_id = str(item["variation_id"])
        if variation_id not in paired_hastus:
            pairs.append({"pair_id": f"|{variation_id}", "status": "not_comparable", "clevercad_variation_id": "", "hastus_variation_id": variation_id, "similarity_percent": None, "difference_count": None, "linked_journeys": 0, "reason": "no sufficiently similar CleverCAD pattern in the same direction"})
    order = {"issues": 0, "ambiguous": 1, "matching": 2, "not_comparable": 3}
    return sorted(pairs, key=lambda item: (order[str(item["status"])], str(item["pair_id"]))), direction_alignment


def _audit_trip_patterns(
    cad_summaries: dict[str, list[TripSummary]],
    hastus_summaries: dict[str, list[TripSummary]],
    final_summaries: dict[str, list[TripSummary]] | None,
    report: ValidationReport,
) -> None:
    if final_summaries is not None:
        for canonical_id, final_variants in final_summaries.items():
            source_variants = cad_summaries.get(canonical_id, []) + hastus_summaries.get(canonical_id, [])
            if not source_variants:
                continue
            for final_trip in final_variants:
                if any(final_trip.schedule_fingerprint == source.schedule_fingerprint for source in source_variants):
                    continue
                if any(final_trip.stop_fingerprint == source.stop_fingerprint for source in source_variants):
                    report.add(
                        "TRP101",
                        "error",
                        "Trip reconciliation",
                        "Merged trip schedule differs from its source",
                        "The ordered stops match, but at least one time or pickup/drop-off value changed during the merge.",
                        file="Final:stop_times.txt",
                        key=final_trip.trip_id,
                        observed=final_trip.schedule_fingerprint[:16],
                        expected="one source schedule fingerprint",
                        context={"source_trip_ids": [item.trip_id for item in source_variants[:10]]},
                    )
                else:
                    report.add(
                        "TRP100",
                        "error",
                        "Trip reconciliation",
                        "Merged trip stop pattern differs from its source",
                        "After translating stop identifiers, the final ordered stop sequence matches neither source record for this trip.",
                        file="Final:stop_times.txt",
                        key=final_trip.trip_id,
                        observed=f"{final_trip.stop_count} stops · {final_trip.stop_fingerprint[:16]}",
                        expected="one source stop-pattern fingerprint",
                        context={"source_trip_ids": [item.trip_id for item in source_variants[:10]]},
                    )

    def by_journey(summaries: dict[str, list[TripSummary]]) -> dict[tuple[str, str, str, str, str], list[TripSummary]]:
        grouped: dict[tuple[str, str, str, str, str], list[TripSummary]] = defaultdict(list)
        for variants in summaries.values():
            for summary in variants:
                grouped[summary.journey_key].append(summary)
        return dict(grouped)

    def variation_catalog(
        summaries: dict[str, list[TripSummary]],
        prefix: str,
    ) -> tuple[dict[str, list[dict[str, object]]], dict[tuple[str, str], str]]:
        grouped: dict[tuple[str, str], list[TripSummary]] = defaultdict(list)
        for variants in summaries.values():
            for summary in variants:
                grouped[(summary.route_short_name, summary.stop_fingerprint)].append(summary)
        by_route: dict[str, list[dict[str, object]]] = defaultdict(list)
        lookup: dict[tuple[str, str], str] = {}
        grouped_by_route: dict[str, list[tuple[str, list[TripSummary]]]] = defaultdict(list)
        for (route_name, fingerprint), trips in grouped.items():
            grouped_by_route[route_name].append((fingerprint, trips))
        for route_name, patterns in grouped_by_route.items():
            patterns.sort(
                key=lambda item: (
                    item[1][0].direction_id,
                    item[1][0].headsign,
                    item[1][0].stop_count,
                    item[1][0].first_time,
                    item[0],
                )
            )
            for number, (fingerprint, trips) in enumerate(patterns, start=1):
                example = min(trips, key=lambda trip: (trip.first_time, trip.last_time, trip.trip_id))
                variation_id = f"{prefix} V{number}"
                lookup[(route_name, fingerprint)] = variation_id
                by_route[route_name].append(
                    {
                        "variation_id": variation_id,
                        "pattern_fingerprint": fingerprint,
                        "_stop_sequence": trips[0].stop_sequence,
                        "example_trip_id": example.trip_id,
                        "stop_count": trips[0].stop_count,
                        "trip_count": len(trips),
                        "shape_ids": sorted({trip.shape_id for trip in trips if trip.shape_id}),
                        "direction_ids": sorted({trip.direction_id for trip in trips if trip.direction_id}),
                        "headsigns": sorted({trip.headsign for trip in trips if trip.headsign}),
                        "first_time": min((trip.first_time for trip in trips if trip.first_time), default=""),
                        "last_time": max((trip.last_time for trip in trips if trip.last_time), default=""),
                        "comparable_journeys": 0,
                        "affected_journeys": 0,
                        "has_problem": False,
                    }
                )
        return dict(by_route), lookup

    cad_journeys = by_journey(cad_summaries)
    hastus_journeys = by_journey(hastus_summaries)
    cad_catalog, cad_variation_lookup = variation_catalog(cad_summaries, "CAD")
    hastus_catalog, hastus_variation_lookup = variation_catalog(hastus_summaries, "HASTUS")
    catalog_entries = {
        **{("CAD", route, item["variation_id"]): item for route, items in cad_catalog.items() for item in items},
        **{("HASTUS", route, item["variation_id"]): item for route, items in hastus_catalog.items() for item in items},
    }
    disagreement_count = 0
    disagreements_by_route: dict[str, int] = defaultdict(int)
    journey_pair_counts: dict[str, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    common_journeys = set(cad_journeys) & set(hastus_journeys)
    for journey_key in sorted(common_journeys):
        route_name = journey_key[0]
        cad_variation_ids = {
            cad_variation_lookup[(route_name, item.stop_fingerprint)] for item in cad_journeys[journey_key]
        }
        hastus_variation_ids = {
            hastus_variation_lookup[(route_name, item.stop_fingerprint)] for item in hastus_journeys[journey_key]
        }
        for variation_id in cad_variation_ids:
            catalog_entries[("CAD", route_name, variation_id)]["comparable_journeys"] += 1
        for variation_id in hastus_variation_ids:
            catalog_entries[("HASTUS", route_name, variation_id)]["comparable_journeys"] += 1
        cad_patterns = {item.stop_fingerprint for item in cad_journeys[journey_key]}
        hastus_patterns = {item.stop_fingerprint for item in hastus_journeys[journey_key]}
        for cad_variation_id in cad_variation_ids:
            for hastus_variation_id in hastus_variation_ids:
                journey_pair_counts[route_name][(cad_variation_id, hastus_variation_id)] += 1
        if cad_patterns & hastus_patterns:
            continue
        disagreement_count += 1
        disagreements_by_route[route_name] += 1
        for variation_id in cad_variation_ids:
            entry = catalog_entries[("CAD", route_name, variation_id)]
            entry["affected_journeys"] += 1
            entry["has_problem"] = True
        for variation_id in hastus_variation_ids:
            entry = catalog_entries[("HASTUS", route_name, variation_id)]
            entry["affected_journeys"] += 1
            entry["has_problem"] = True
        cad_example = cad_journeys[journey_key][0]
        hastus_example = hastus_journeys[journey_key][0]
        cad_variation_id = cad_variation_lookup[(route_name, cad_example.stop_fingerprint)]
        hastus_variation_id = hastus_variation_lookup[(route_name, hastus_example.stop_fingerprint)]
        report.add(
            "TRP102",
            "warning",
            "Trip reconciliation",
            "CleverCAD and HASTUS trip patterns disagree",
            "Trips with the same route, direction, headsign, start, and end times have different translated stop sequences.",
            file="CleverCAD/HASTUS:stop_times.txt",
            key=" | ".join(journey_key),
            observed=f"CAD {cad_example.trip_id}: {cad_example.stop_count} stops",
            expected=f"HASTUS {hastus_example.trip_id}: {hastus_example.stop_count} stops",
            context={
                "clevercad_trip_id": cad_example.trip_id,
                "hastus_trip_id": hastus_example.trip_id,
                "route_short_name": cad_example.route_short_name,
                "direction_id": cad_example.direction_id,
                "headsign": cad_example.headsign,
                "first_time": cad_example.first_time,
                "last_time": cad_example.last_time,
                "clevercad_variation_id": cad_variation_id,
                "hastus_variation_id": hastus_variation_id,
                "clevercad_shape_id": cad_example.shape_id,
                "hastus_shape_id": hastus_example.shape_id,
                "clevercad_variation_ids": sorted(cad_variation_ids),
                "hastus_variation_ids": sorted(hastus_variation_ids),
                "clevercad_shape_ids": sorted({item.shape_id for item in cad_journeys[journey_key] if item.shape_id}),
                "hastus_shape_ids": sorted({item.shape_id for item in hastus_journeys[journey_key] if item.shape_id}),
            },
        )

    route_names = sorted(
        {key[0] for key in cad_journeys} | {key[0] for key in hastus_journeys},
        key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value),
    )
    route_health = []
    final_by_route: dict[str, dict[str, list[TripSummary]]] = defaultdict(lambda: defaultdict(list))
    for variants in (final_summaries or {}).values():
        for trip in variants:
            final_by_route[trip.route_short_name][trip.stop_fingerprint].append(trip)
    for route_name in route_names:
        cad_count = sum(key[0] == route_name for key in cad_journeys)
        hastus_count = sum(key[0] == route_name for key in hastus_journeys)
        compared = sum(key[0] == route_name for key in common_journeys)
        mismatches = disagreements_by_route.get(route_name, 0)
        matches = compared - mismatches
        cad_variations = cad_catalog.get(route_name, [])
        hastus_variations = hastus_catalog.get(route_name, [])
        variation_pairs, direction_alignment = _pair_route_variations(cad_variations, hastus_variations, journey_pair_counts.get(route_name, {}))
        final_variations = []
        for index, (fingerprint, trips) in enumerate(sorted(final_by_route.get(route_name, {}).items()), 1):
            final_variations.append({"variation_id": f"Final V{index}", "pattern_fingerprint": fingerprint,
                "example_trip_id": trips[0].trip_id, "trip_count": len(trips), "stop_count": trips[0].stop_count,
                "direction_ids": sorted({trip.direction_id for trip in trips}),
                "headsigns": sorted({trip.headsign for trip in trips}), "shape_ids": sorted({trip.shape_id for trip in trips})})
        for pair in variation_pairs:
            cad_pattern = next((item for item in cad_variations if item["variation_id"] == pair["clevercad_variation_id"]), None)
            hastus_pattern = next((item for item in hastus_variations if item["variation_id"] == pair["hastus_variation_id"]), None)
            pair["final_matches"] = [{**item, "matches_source": "Both" if cad_pattern and hastus_pattern and item["pattern_fingerprint"] == cad_pattern["pattern_fingerprint"] == hastus_pattern["pattern_fingerprint"] else "CleverCAD" if cad_pattern and item["pattern_fingerprint"] == cad_pattern["pattern_fingerprint"] else "HASTUS"}
                for item in final_variations if any(source and source["pattern_fingerprint"] == item["pattern_fingerprint"] for source in (cad_pattern, hastus_pattern))]
        cad_by_variation = {str(item["variation_id"]): item for item in cad_variations}
        hastus_by_variation = {str(item["variation_id"]): item for item in hastus_variations}
        paired = [item for item in variation_pairs if item["status"] != "not_comparable"]
        affected_pairs = [item for item in paired if item["status"] == "issues"]
        ambiguous_pairs = [item for item in paired if item["status"] == "ambiguous"]
        unpaired_pairs = [item for item in variation_pairs if item["status"] == "not_comparable"]
        for pair in affected_pairs:
            cad_item = cad_by_variation[str(pair["clevercad_variation_id"])]
            hastus_item = hastus_by_variation[str(pair["hastus_variation_id"])]
            cad_item["has_problem"] = True
            hastus_item["has_problem"] = True
            report.add(
                "TRP103",
                "warning",
                "Trip reconciliation",
                "CleverCAD and HASTUS route variations disagree",
                "The most likely patterns for this route and direction have different translated stop sequences.",
                file="CleverCAD/HASTUS:stop_times.txt",
                key=f"{route_name} | {cad_item['variation_id']} | {hastus_item['variation_id']}",
                observed=f"CAD {cad_item['example_trip_id']}: {cad_item['stop_count']} stops",
                expected=f"HASTUS {hastus_item['example_trip_id']}: {hastus_item['stop_count']} stops",
                context={
                    "clevercad_trip_id": cad_item["example_trip_id"],
                    "hastus_trip_id": hastus_item["example_trip_id"],
                    "route_short_name": route_name,
                    "clevercad_variation_id": cad_item["variation_id"],
                    "hastus_variation_id": hastus_item["variation_id"],
                    "clevercad_shape_id": ", ".join(str(value) for value in cad_item["shape_ids"]),
                    "hastus_shape_id": ", ".join(str(value) for value in hastus_item["shape_ids"]),
                    "similarity_percent": pair["similarity_percent"],
                    "difference_count": pair["difference_count"],
                    "pairing_reason": pair["reason"],
                },
            )
        comparable_cad_ids = {str(item["clevercad_variation_id"]) for item in paired}
        comparable_hastus_ids = {str(item["hastus_variation_id"]) for item in paired}
        affected_cad = [item for item in cad_variations if item["has_problem"]]
        affected_hastus = [item for item in hastus_variations if item["has_problem"]]
        if not affected_pairs:
            variation_scope = "none"
        elif len(affected_pairs) == len(paired):
            variation_scope = "all_comparable_variations"
        else:
            variation_scope = "specific_variations"
        route_status = "not_comparable" if not paired else ("issues" if affected_pairs or unpaired_pairs else ("ambiguous" if ambiguous_pairs else "healthy"))
        public_cad_variations = [{key: value for key, value in item.items() if not key.startswith("_")} for item in cad_variations]
        public_hastus_variations = [{key: value for key, value in item.items() if not key.startswith("_")} for item in hastus_variations]
        route_health.append(
            {
                "route_short_name": route_name,
                "clevercad_journeys": cad_count,
                "hastus_journeys": hastus_count,
                "compared_journeys": compared,
                "matching_journeys": matches,
                "mismatch_journeys": mismatches,
                "match_percent": round(matches * 100 / compared, 1) if compared else None,
                "status": route_status,
                "clevercad_variation_count": len(cad_variations),
                "hastus_variation_count": len(hastus_variations),
                "comparable_clevercad_variations": len(comparable_cad_ids),
                "comparable_hastus_variations": len(comparable_hastus_ids),
                "affected_clevercad_variations": len(affected_cad),
                "affected_hastus_variations": len(affected_hastus),
                "paired_variation_count": len(paired),
                "mismatch_variation_count": len(affected_pairs),
                "ambiguous_variation_count": len(ambiguous_pairs),
                "unpaired_variation_count": len(unpaired_pairs),
                "direction_alignment": direction_alignment,
                "variation_scope": variation_scope,
                "variation_pairs": variation_pairs,
                "final_variations": final_variations,
                "clevercad_variations": public_cad_variations,
                "hastus_variations": public_hastus_variations,
            }
        )

    report.stats["trip_reconciliation"] = {
        "clevercad_canonical_trips": len(cad_summaries),
        "hastus_canonical_trips": len(hastus_summaries),
        "common_scheduled_journeys": len(set(cad_journeys) & set(hastus_journeys)),
        "source_pattern_disagreements": disagreement_count,
        "route_health": route_health,
    }
    if final_summaries is not None:
        report.stats["trip_reconciliation"]["final_canonical_trips"] = len(final_summaries)


def _audit_stops(
    cad: SourceFeed,
    hastus: SourceFeed,
    final: SourceFeed | None,
    report: ValidationReport,
) -> None:
    cad_by_id = _index_unique(cad.stops, "stop_id")
    cad_by_code = _group(cad.stops, "stop_code")
    hastus_by_id = _index_unique(hastus.stops, "stop_id")
    final_by_id = _index_unique(final.stops, "stop_id") if final else {}

    ambiguous_codes = {code: rows for code, rows in cad_by_code.items() if len(rows) > 1 and code in hastus_by_id}
    for code, rows in sorted(ambiguous_codes.items()):
        report.add(
            "STP001",
            "error",
            "Stop reconciliation",
            "Ambiguous CleverCAD-to-HASTUS stop mapping",
            "The CleverCAD operational stop code maps to more than one CleverCAD stop record.",
            file="CleverCAD:stops.txt",
            key=code,
            observed=", ".join(row.get("stop_id", "") for row in rows),
            expected="one stop_id",
        )

    hastus_to_final = _hastus_stop_translation(cad, hastus, final)
    mapping_issues: list[dict[str, object]] = []

    if final:
        for stop_id, cad_stop in sorted(cad_by_id.items()):
            if stop_id in final_by_id:
                continue
            report.add(
                "STP002",
                "error" if stop_id in cad.used_stop_ids else "warning",
                "Stop reconciliation",
                "CleverCAD stop is missing from the merged GTFS",
                "No final stops.txt record retains this CleverCAD stop_id.",
                file="Final:stops.txt",
                key=stop_id,
                observed="missing",
                expected=cad_stop.get("stop_name", "source stop"),
            )

        for stop_id, hastus_stop in sorted(hastus_by_id.items()):
            if stop_id in hastus_to_final:
                continue
            report.add(
                "STP003",
                "error" if stop_id in hastus.used_stop_ids else "warning",
                "Stop reconciliation",
                "HASTUS stop is missing from the merged GTFS",
                "No direct or crosswalked final stop could be found.",
                file="Final:stops.txt",
                key=stop_id,
                observed="missing",
                expected=hastus_stop.get("stop_name", "source stop"),
            )

        known_final_ids = set(cad_by_id) | set(hastus_to_final.values())
        for stop_id, final_stop in sorted(final_by_id.items()):
            if stop_id not in known_final_ids:
                report.add(
                    "STP004",
                    "error",
                    "Stop reconciliation",
                    "Merged stop has no source record",
                    "The final stop is not traceable to CleverCAD or HASTUS.",
                    file="Final:stops.txt",
                    key=stop_id,
                    observed=final_stop.get("stop_name", ""),
                )

    for hastus_id, final_id in sorted(hastus_to_final.items()):
        hastus_stop = hastus_by_id[hastus_id]
        final_stop = final_by_id.get(final_id)
        cad_matches = cad_by_code.get(hastus_id, [])
        cad_stop = cad_matches[0] if len(cad_matches) == 1 else cad_by_id.get(final_id)
        sources = [row for row in (cad_stop, hastus_stop) if row]

        if cad_stop:
            differences: list[dict[str, object]] = []
            cad_name = _normalize_name(cad_stop.get("stop_name", ""))
            hastus_name = _normalize_name(hastus_stop.get("stop_name", ""))
            if cad_name and hastus_name and cad_name != hastus_name:
                differences.append({"field": "stop_name", "clevercad": cad_stop.get("stop_name", ""), "hastus": hastus_stop.get("stop_name", "")})
                report.add(
                    "STP005",
                    "warning",
                    "Stop reconciliation",
                    "Source stop names disagree",
                    "CleverCAD and HASTUS identify the mapped stop with different names.",
                    file="CleverCAD/HASTUS:stops.txt",
                    key=f"{final_id} ↔ {hastus_id}",
                    observed=f"CAD: {cad_stop.get('stop_name', '')} | HASTUS: {hastus_stop.get('stop_name', '')}",
                    context={
                        "clevercad_stop_id": final_id,
                        "hastus_stop_id": hastus_id,
                    },
                )
            distance = _distance_m(cad_stop, hastus_stop)
            if distance is not None and distance > 35:
                differences.append({"field": "coordinates", "clevercad": f"{cad_stop.get('stop_lat', '')}, {cad_stop.get('stop_lon', '')}", "hastus": f"{hastus_stop.get('stop_lat', '')}, {hastus_stop.get('stop_lon', '')}", "distance_m": round(distance, 1)})
                report.add(
                    "STP006",
                    "warning",
                    "Stop reconciliation",
                    "Mapped source stops are far apart",
                    f"The mapped CleverCAD and HASTUS coordinates are {distance:.1f} metres apart.",
                    file="CleverCAD/HASTUS:stops.txt",
                    key=f"{final_id} ↔ {hastus_id}",
                    observed=f"{distance:.1f} m",
                    expected="≤ 35 m or an approved exception",
                    context={
                        "clevercad_stop_id": final_id,
                        "hastus_stop_id": hastus_id,
                        "distance_m": round(distance, 1),
                    },
                )
            metadata_differences: list[dict[str, object]] = []
            for column in ("location_type", "wheelchair_boarding", "platform_code", "zone_id", "stop_desc"):
                cad_value = cad_stop.get(column, "").strip()
                hastus_value = hastus_stop.get(column, "").strip()
                cad_comparable = cad_value or ("0" if column in {"location_type", "wheelchair_boarding"} else "")
                hastus_comparable = hastus_value or ("0" if column in {"location_type", "wheelchair_boarding"} else "")
                if (cad_comparable or hastus_comparable) and _normalize_name(cad_comparable) != _normalize_name(hastus_comparable):
                    metadata_differences.append({"field": column, "clevercad": cad_value, "hastus": hastus_value})
            cad_parent = cad_stop.get("parent_station", "").strip()
            hastus_parent_source = hastus_stop.get("parent_station", "").strip()
            hastus_parent = hastus_to_final.get(hastus_parent_source, hastus_parent_source)
            if (cad_parent or hastus_parent) and cad_parent != hastus_parent:
                metadata_differences.append({"field": "parent_station", "clevercad": cad_parent, "hastus": hastus_parent_source, "hastus_mapped": hastus_parent})
            if metadata_differences:
                differences.extend(metadata_differences)
                fields = ", ".join(str(item["field"]) for item in metadata_differences)
                report.add(
                    "STP010",
                    "warning",
                    "Stop reconciliation",
                    "Mapped source stop attributes disagree",
                    f"The mapped CleverCAD and HASTUS stops differ in: {fields}.",
                    file="CleverCAD/HASTUS:stops.txt",
                    key=f"{final_id} ↔ {hastus_id}",
                    observed=" | ".join(f"{item['field']}: {item['clevercad'] or 'blank'}" for item in metadata_differences),
                    expected=" | ".join(f"{item['field']}: {item['hastus'] or 'blank'}" for item in metadata_differences),
                    context={"clevercad_stop_id": final_id, "hastus_stop_id": hastus_id, "fields": [item["field"] for item in metadata_differences]},
                )
            if differences:
                mapping_issues.append(
                    {
                        "clevercad_stop_id": final_id,
                        "hastus_stop_id": hastus_id,
                        "clevercad_stop_name": cad_stop.get("stop_name", ""),
                        "hastus_stop_name": hastus_stop.get("stop_name", ""),
                        "distance_m": round(distance, 1) if distance is not None else None,
                        "difference_fields": [str(item["field"]) for item in differences],
                        "differences": differences,
                        "clevercad": cad_stop,
                        "hastus": hastus_stop,
                    }
                )

        if final_stop is None:
            continue

        final_name = _normalize_name(final_stop.get("stop_name", ""))
        source_names = {_normalize_name(row.get("stop_name", "")) for row in sources}
        if final_name and source_names and final_name not in source_names:
            report.add(
                "STP007",
                "error",
                "Stop reconciliation",
                "Merged stop name matches neither source",
                "The final rider-facing name cannot be traced to CleverCAD or HASTUS.",
                file="Final:stops.txt",
                key=final_id,
                observed=final_stop.get("stop_name", ""),
                expected=" | ".join(row.get("stop_name", "") for row in sources),
            )
        distances = [distance for row in sources if (distance := _distance_m(final_stop, row)) is not None]
        if distances and min(distances) > 15:
            report.add(
                "STP008",
                "error",
                "Stop reconciliation",
                "Merged stop coordinates match neither source",
                f"The closest source coordinate is {min(distances):.1f} metres away.",
                file="Final:stops.txt",
                key=final_id,
                observed=f"{min(distances):.1f} m",
                expected="≤ 15 m from at least one source",
            )

        for column in ("stop_code", "location_type", "parent_station", "platform_code"):
            expected = hastus_stop.get(column, "").strip()
            actual = final_stop.get(column, "").strip()
            if expected and actual != expected:
                report.add(
                    "STP009",
                    "error",
                    "Stop reconciliation",
                    "HASTUS station metadata was not preserved",
                    f"The merged {column} differs from the mapped HASTUS stop.",
                    file="Final:stops.txt",
                    key=final_id,
                    observed=actual or "blank",
                    expected=expected,
                    context={"hastus_stop_id": hastus_id, "column": column},
                )

    report.stats["stop_crosswalk"] = {
        "clevercad_stops": len(cad_by_id),
        "hastus_stops": len(hastus_by_id),
        "source_stop_mappings": len(hastus_to_final),
        "mapped_stop_mismatches": len(mapping_issues),
        "ambiguous_operational_codes": len(ambiguous_codes),
        "mapping_issues": mapping_issues,
    }
    if final:
        report.stats["stop_crosswalk"]["final_stops"] = len(final_by_id)


def _audit_entity_provenance(cad: SourceFeed, hastus: SourceFeed, final: SourceFeed, report: ValidationReport) -> None:
    cad_route_ids = {row.get("route_id", "") for row in cad.routes}
    hastus_route_ids = {row.get("route_id", "") for row in hastus.routes}
    final_route_ids = {row.get("route_id", "") for row in final.routes}
    for route_id in sorted(final_route_ids - cad_route_ids - hastus_route_ids):
        report.add(
            "MRG101",
            "error",
            "Merge provenance",
            "Merged route has no source route",
            "The final route_id is not present in either source export.",
            file="Final:routes.txt",
            key=route_id,
        )

    cad_trip_ids = {_source_trip_id(row) for row in cad.trips}
    hastus_trip_ids = {_source_trip_id(row) for row in hastus.trips}
    final_trip_ids = {_source_trip_id(row) for row in final.trips}
    for trip_id in sorted(final_trip_ids - cad_trip_ids - hastus_trip_ids):
        report.add(
            "MRG102",
            "error",
            "Merge provenance",
            "Merged trip has no source trip",
            "The final trip_id cannot be traced to either source, including HASTUS service suffix normalization.",
            file="Final:trips.txt",
            key=trip_id,
        )

    for shape_id in sorted(final.shape_ids - cad.shape_ids - hastus.shape_ids):
        report.add(
            "MRG103",
            "error",
            "Merge provenance",
            "Merged shape has no source shape",
            "The final shape_id is not present in either source export.",
            file="Final:shapes.txt",
            key=shape_id,
        )
    for service_id in sorted(final.service_ids - cad.service_ids - hastus.service_ids):
        report.add(
            "MRG104",
            "error",
            "Merge provenance",
            "Merged service has no source service",
            "The final service_id is not present in either source export.",
            file="Final:calendar.txt",
            key=service_id,
        )

    report.stats["merge_provenance"] = {
        "final_routes_traceable": len(final_route_ids & (cad_route_ids | hastus_route_ids)),
        "final_routes_total": len(final_route_ids),
        "final_trips_traceable": len(final_trip_ids & (cad_trip_ids | hastus_trip_ids)),
        "final_trips_total": len(final_trip_ids),
        "final_shapes_traceable": len(final.shape_ids & (cad.shape_ids | hastus.shape_ids)),
        "final_shapes_total": len(final.shape_ids),
        "final_services_traceable": len(final.service_ids & (cad.service_ids | hastus.service_ids)),
        "final_services_total": len(final.service_ids),
    }


def validate_exports(
    clevercad_path: str | Path,
    hastus_path: str | Path,
    final_path: str | Path | None = None,
) -> ValidationReport:
    final_value = str(final_path).strip() if final_path is not None else ""
    if final_value:
        report = validate_feed(final_value)
        report.stats["final_technical_findings"] = [item.to_dict() for item in report.findings]
        report.profile = "oc-transpo-source-and-final-audit"
    else:
        report = ValidationReport(
            source_path=f"CleverCAD: {clevercad_path} | HASTUS: {hastus_path}",
            profile="oc-transpo-source-preflight",
        )
    cad = _load_source(clevercad_path, "CleverCAD", report)
    hastus = _load_source(hastus_path, "HASTUS", report)
    final = _load_source(final_value, "Final merged GTFS", report) if final_value else None
    loaded = [feed for feed in (cad, hastus, final) if feed]
    try:
        report.stats["inputs"] = {
            feed.label: {"path": str(feed.path), "sha256": feed.sha256}
            for feed in loaded
        }
        if cad and hastus:
            hastus_translation = _hastus_stop_translation(cad, hastus)
            cad_summaries = _trip_summaries(cad, {}, report)
            hastus_summaries = _trip_summaries(hastus, hastus_translation, report)
            final_summaries = _trip_summaries(final, {}, report) if final else None
            _audit_stops(cad, hastus, final, report)
            if final:
                _audit_entity_provenance(cad, hastus, final, report)
            if cad_summaries and hastus_summaries and (final_summaries or final is None):
                _audit_trip_patterns(cad_summaries, hastus_summaries, final_summaries, report)
    finally:
        for feed in loaded:
            feed.close()
    report.finish()
    return report


def validate_merge(
    clevercad_path: str | Path,
    hastus_path: str | Path,
    final_path: str | Path | None = None,
) -> ValidationReport:
    """Backward-compatible alias for the optional-final export audit."""
    return validate_exports(clevercad_path, hastus_path, final_path)
