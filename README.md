# GTFS Release Validator

I built this tool to make GTFS exports easier to inspect before and after a feed is merged for publication. Transit data can be structurally valid and still lose a stop, change a trip pattern, or carry inconsistent information between scheduling systems. I wanted a way to trace those differences back to the source records.

The application brings together individual feed inspection, CleverCAD and HASTUS bus comparisons, HASTUS rail review, final-feed validation, and an experimental merge candidate builder. Feed processing stays on the workstation, and the original archives remain unchanged.

## What it does

- Inspect a single source or final GTFS feed, or review several exports together.
- Browse routes, variations, trips, stops, calendars, shapes, and raw tables through an indexed viewer.
- Compare bus exports using translated stop identifiers and ordered stop patterns.
- Highlight missing stops, changed sequences, ambiguous mappings, and differences in stop attributes.
- Compare source trips with a final feed, including operating dates, times, boarding rules, and shape geometry.
- Inspect rail exports separately and compare them with the final feed.
- Read HASTUS export diagnostics alongside the affected routes and trips.
- Review archive health, core GTFS relationships, agency-specific checks, and optional MobilityData validator results.
- Export findings and supporting records as JSON, CSV, Excel workbooks, and printable reports.

## Main areas

- **Individual feeds:** Review each export's contents, technical findings, route health, and source diagnostics.
- **Source comparison:** Investigate bus variations and stop mappings with both source records available for context.
- **Rail review:** Follow rail routes, trips, service calendars, and differences against the final feed.
- **Final validation:** Keep technical findings, agency expectations, and canonical validator results distinct.
- **Merge candidate builder:** Produce a new draft feed with a receipt documenting source matches, warnings, exclusions, and validation findings.

The application also includes my [GTFS Viewer](https://github.com/Omar-Khattab-01/gtfs-viewer) for reading feed files with coloured columns and issue highlights.

## Review limits

I designed the tool to make evidence easier to inspect, rather than treat every difference as a confirmed service defect. An unpaired variation needs review; it does not by itself prove that service is missing. Agency-specific expectations are shown separately from GTFS requirements.

The merge builder is experimental. Its output is a draft for review, and a successful build does not establish publication approval. Core schedule checks are focused in scope; unavailable validation engines are reported explicitly.

## Attribution

Bundled components and validation-engine attribution are recorded in [THIRD_PARTY.md](THIRD_PARTY.md).
