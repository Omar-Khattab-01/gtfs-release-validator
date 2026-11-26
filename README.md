# GTFS Validator

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

- **Feeds:** Review each export’s files, routes, findings and source diagnostics. Filter by level and issue type; paged lists and evidence panels keep your place.
- **Schedule calendar** shows Bus, Line 1, and Lines 2 & 4 by service date. Filter a route to verify its trips, calendar exceptions, and exported colors.
- **Headways & blocks** calculates departure gaps from `stop_times.txt`. Filter by route, date, direction and variation. Rail defaults to each variation’s actual departure station, including short trips. A terminus-only view remains available for Lines 1, 2 and 4, with Trim activated when served. Station platforms are grouped, and gaps remain separate for each station and direction. Trip rows show their actual origin, variation, shape and block.
- **Settings** holds validation options, Java/JAR and reference paths, and saved indexes. Export inputs start blank; paste a path or use **Browse**. Use **Manage saved exports** to offload an individual feed's index and related audits or all saved cache data.
- **Source comparison:** Investigate bus variations and stop mappings with both source records available for context.
- **Rail review:** Follow rail routes, trips, service calendars, and differences against the final feed.
- **Validation:** Review MobilityData first, then OC Transpo and GTFS checks. Each engine has file/level filters and paged findings. Calendar checks summarize start timing relative to the selected validation date, inclusive coverage length, and scheduled service days after calendar exceptions. Future and expired exports are flagged; no Friday start or fixed one-month duration is imposed.

- **Packaging:** Review stored ZIP modes separately from extracted modes. Missing Unix metadata and modes such as `0644` or `0666` are accepted; stored `0600` is flagged. **Test extraction** checks a temporary copy without modifying the source. On Windows, Unix permissions are read from ZIP metadata; extracted files use Windows attributes.
- **Evidence:** Files, trips, route variations and the advanced viewer open in panels. Back restores the previous evidence view; Close returns to the same list and filters.
- **Progress:** A green stage bar and elapsed timer track validation. Status polling omits the large report until completion. Comparison parsing avoids per-row dictionaries and reuses identical stop-pattern fingerprints.

The application also includes my [GTFS Viewer](https://github.com/Omar-Khattab-01/gtfs-viewer) for reading feed files with coloured columns and issue highlights.

On Windows, extract an update into a fresh folder and run `start_windows.bat` there. The launcher prints the version and application folder. If the usual port is occupied, it opens this copy on a free local port; use the newly opened browser tab. The version is shown in the footer. You can carry over `.local-tools` to retain the MobilityData JAR; saved Java settings remain in your user settings and do not select the app version.

## Review limits

I designed the tool to make evidence easier to inspect, rather than treat every difference as a confirmed service defect. An unpaired variation needs review; it does not by itself prove that service is missing. Agency-specific expectations are shown separately from GTFS requirements.

Cached paths are checked using file identity, size, timestamps and short content samples. Changed inputs are hashed again. The fresh-validation option fully rechecks file fingerprints. Matching audits remain specific to the validation day and selected checks.

The experimental merge builder is paused. Core schedule checks are focused in scope; unavailable validation engines are reported explicitly.

## Attribution

Bundled components and validation-engine attribution are recorded in [THIRD_PARTY.md](THIRD_PARTY.md).
