# GTFS Release Validator

I built this tool to make GTFS exports easier to inspect before and after a feed is merged for publication. Transit data can be structurally valid and still lose a stop, change a trip pattern, or carry inconsistent information between scheduling systems. I wanted a way to trace those differences back to the source records.

The application brings together individual feed inspection, CleverCAD and HASTUS bus comparisons, HASTUS rail review, final-feed validation, and scheduled headway checks. Feed processing stays on the workstation, and the original archives remain unchanged.

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
- **Schedule calendar** shows Bus, Line 1, and Lines 2 & 4 by service date. Filter a route to verify its trips, calendar exceptions, and exported colors.
- **Headways & blocks** calculates hourly departure counts and gaps from `stop_times.txt` for a selected date, direction and boarding stop. Lines 1, 2 and 4 default to terminus departures, with station platforms grouped and origin/destination names beside directions. Line 1 supports Tunney’s Pasture, Blair and future Trim when served; Line 2 uses Bayview and Limebank; Line 4 uses South Keys and Airport. Short trips remain visible, while gaps are kept separate for each originating terminus and direction. Review trip attributes, block IDs, overlapping block times, simultaneous departures and optional gap thresholds.
- **Saved exports** reopens indexed paths and matching audits. Use **Manage saved exports** to offload an individual feed's index and related audits or all saved cache data.
- **Source comparison:** Investigate bus variations and stop mappings with both source records available for context.
- **Rail review:** Follow rail routes, trips, service calendars, and differences against the final feed.
- **Final validation:** Keep technical findings, agency expectations, and canonical validator results distinct.

The application also includes my [GTFS Viewer](https://github.com/Omar-Khattab-01/gtfs-viewer) for reading feed files with coloured columns and issue highlights.

On Windows, extract an update into a fresh folder and run `start_windows.bat` there. The launcher prints the version and application folder. If the usual port is occupied, it opens this copy on a free local port; use the newly opened browser tab. The version is also shown at the top of the page. You can carry over `.local-tools` to retain the MobilityData JAR; saved Java settings remain in your user settings and do not select the app version.

## Review limits

I designed the tool to make evidence easier to inspect, rather than treat every difference as a confirmed service defect. An unpaired variation needs review; it does not by itself prove that service is missing. Agency-specific expectations are shown separately from GTFS requirements.

Cached paths are checked using file identity, size, timestamps and short content samples. Changed inputs are hashed again. The fresh-validation option fully rechecks file fingerprints. Matching audits remain specific to the validation day and selected checks.

The experimental merge builder is paused. Core schedule checks are focused in scope; unavailable validation engines are reported explicitly.

## Attribution

Bundled components and validation-engine attribution are recorded in [THIRD_PARTY.md](THIRD_PARTY.md).
