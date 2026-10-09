# OC Transpo GTFS Merge Auditor

This local Windows application first reconciles the two source exports before they are submitted to the vendor:

1. CleverCAD export (`CW-…zip`)
2. HASTUS export (`GTFS_…zip`)

After the vendor produces the merged feed, a final merged/publication GTFS can be supplied as an optional third input for post-merge verification.

All three archives are read-only and remain on the workstation.

The interface also accepts **only a final ZIP**: leave both source paths empty
and select **Validate & inspect**. The existing Python validator checks the file
and the Local feed viewer lets you browse routes, variations, individual trips,
stops, shapes, and paginated GTFS tables. Shapes use an offline coordinate plot.

When all three feeds are supplied, open a route variation to see a final column
alongside CleverCAD and HASTUS. The final pattern selector lists exact source
pattern matches first, with other final patterns available for manual review.
Multiple final patterns can preserve different source variations; the interface
does not claim the vendor chose one source for the entire route. Source labels
mean stop-pattern equivalence, not proof of vendor intent or schedule equality.

Source-only variations open their own stop sequence. The Local feed viewer can
inspect all their trips and shapes, even when no counterpart exists.

Your [GTFS Viewer](https://github.com/Omar-Khattab-01/gtfs-viewer) is bundled at
`http://127.0.0.1:8765/file-viewer/`, accessible from the Local feed viewer.
It supports opening ZIPs directly, coloured columns, virtual scrolling, feed
checks, and issue highlights. Its files are read directly in the browser and
never uploaded. No Node installation is needed to run the bundled viewer.
Build attribution is recorded in THIRD_PARTY.md.

### Fast local browsing

During the first audit, the **Preparing fast browsing** stage streams each
archive into a disk-backed SQLite index. Routes, trips, comparison
evidence, shapes, and raw-table pages then use indexed lookups rather than
repeatedly decompressing and scanning entire GTFS tables. The original ZIPs
are never edited or unpacked into your project directory.

With **Save indexes** enabled, all supplied feeds (both sources and the optional
final) are saved automatically. SHA-256 content fingerprints and a schema version
prevent reuse for changed feeds. Reopening after restarting reuses the saved
database; validation still runs afresh. Disabling this option uses temporary
indexes. First-time indexing still takes time.

Windows storage: `%LOCALAPPDATA%\GTFS Merge Auditor\cache`. Override with
`GTFS_VALIDATOR_CACHE_DIR`. Parsed feed data stays on disk, potentially larger
than uncompressed GTFS. The cache has a 10 GB budget and removes unused entries
older than 30 days when saving new indexes. Active indexes are protected.
**Remove unused saved indexes** reclaims storage without deleting original ZIPs.
If saving fails or the budget is exceeded, browsing uses a session-only index
and shows a warning.

### Final merged GTFS validation

The **Final GTFS validation** tab separates three independent checks:

- Existing technical and ZIP checks.
- Your supplied Python agency profile, grouped by file, with expandable evidence.
  Row findings open the local table at that CSV row. Your supplied
  `routes_sort_order_list.csv` is bundled; a local override is available.
  Agency expectations, known exceptions and empty-field rules are not universal
  GTFS requirements. Friday/one-month release policy can be disabled independently.
- MobilityData's canonical validator, run as a local Java process, with notice
  groups, sample evidence and downloadable reports. Unavailable engines and
  failures are explicitly reported, never represented as passes.

The validation date is configurable. Large profile tables are processed in
25,000-row batches. Each file keeps up to 250 examples per severity; counts
include all findings. MobilityData provides its own sampled notices. Download
final validation evidence separately from the source-comparison report.
No feed is uploaded to MobilityData.

## Windows setup and launch

Requirements: Windows 10/11 and Python 3.10 or newer from <https://www.python.org/downloads/windows/>. During Python installation, enable **Add Python to PATH** and install the Python launcher.

Double-click:

```text
start_windows.bat
```

The launcher checks Python, installs pandas and tzdata from `requirements.txt`
if missing, starts the server, and opens <http://127.0.0.1:8765>. Keep the command
window open while using the tool. Press `Ctrl+C` to stop it.

For MobilityData checks, install Java 17 or newer and run
`setup_mobilitydata.bat` once. It downloads the CLI JAR from MobilityData's
official GitHub release into `.local-tools` (not committed to Git). Alternatively,
supply an existing local CLI JAR path in the form. The Java process has a 2 GB
heap cap and 15-minute timeout; large feeds need sufficient RAM and temporary
disk space. Internet is needed for initial dependency/JAR setup only; all feed
processing runs locally.

## Command line

Required pre-vendor source audit:

```powershell
py -3 -m gtfs_validator audit "C:\GTFS\CW-EXPORT.zip" "C:\GTFS\HASTUS-EXPORT.zip" --output source-report.json
```

Optional source plus final-feed audit:

```powershell
py -3 -m gtfs_validator audit "C:\GTFS\CW-EXPORT.zip" "C:\GTFS\HASTUS-EXPORT.zip" "C:\GTFS\FINAL-MERGED.zip" --output merge-report.json
```

Final-feed-only technical validation:

```powershell
py -3 -m gtfs_validator validate "C:\GTFS\FINAL-MERGED.zip" --output final-report.json
```

Exit codes are `0` for eligible, `1` for needs review, and `2` for blocked.

## Reconciliation model

Source comparison rules are generic, not route- or incident-specific. Previous
incidents are test cases for general rules. The optional supplied agency profile
retains your agency's known exceptions and is labeled separately. CleverCAD and
HASTUS are required only for source comparison; final-only validation is supported.

For stops, it builds a crosswalk from the source identifiers:

- CleverCAD commonly uses the public/numeric value in `stop_id` and the operational code in `stop_code`.
- HASTUS commonly uses the operational code in `stop_id` and a public/station value in `stop_code`.
- The final feed is checked against both direct identifiers and the resulting crosswalk.

The audit currently detects:

- ambiguous CleverCAD-to-HASTUS stop mappings;
- source stops missing from the final feed;
- source name or coordinate disagreement;
- equivalent CleverCAD/HASTUS journeys with different ordered stop patterns;
- ambiguous cross-source identifier mappings.

When the optional final feed is supplied, it additionally detects:

- source stops missing from the final feed and final stops with no source;
- final stop names/coordinates matching neither source;
- lost HASTUS station, platform, location-type, or stop-code metadata;
- final routes, trips, shapes, or services with no source record;
- changed final stop patterns, times, or pickup/drop-off rules;
- HASTUS trip identifiers whose service suffix is removed by the merge;
- all final-feed ZIP, structure, relationship, coordinate, and stop-time issues.

## Final artifact checks

- ZIP CRC, duplicate members, unsafe paths, encryption, compression limits, and root layout
- stored and system-extracted readability (`0600` is blocked; `0644` recommended;
  `0666` is readable; absent Windows/DOS Unix modes are informational)
- required files/columns, UTF-8 and CSV structure, empty tables, and primary keys
- route/trip/service/shape/stop and parent-station relationships
- stop coordinates and route colours
- stop-time syntax, arrival/departure order, duplicate sequences, and nondecreasing trip times
- orphan shapes
- grouped issue cards and progressive loading so large reports remain navigable
- route-health dashboard covering healthy, mismatched, and non-comparable routes
- route-variation inventory based on translated ordered stop patterns, with trip counts and source shape IDs
- all-versus-specific variation impact classification and one-click variation filtering
- compact variation tabs for mismatched, matching, and source-only patterns, with on-demand stop-by-stop comparison
- route-level direction alignment inferred from translated stop patterns, including feeds that use opposite `direction_id` conventions
- variation pairing based on translated stop-sequence similarity, so an added terminal stop or different headsign does not prevent comparison
- an explicit ambiguous-pairing state when more than one counterpart is similarly plausible
- route sorting by route number, attention priority, or variation count
- a dedicated stop-mapping tab for names, coordinates, accessibility, platform, station, zone, and descriptive attribute differences
- clickable evidence drawers with full source stop records
- offline coordinate maps for mapped-stop location disagreements
- aligned trip comparisons that distinguish missing, extra, changed, and schedule-different stops
- expandable mismatch evidence with every available stops.txt field from both exports
- selection exports and a purpose-built affected-stops CSV
- searchable findings and complete JSON/CSV report downloads

## Current next steps

The next comparison layers are calendar expansion on actual operating dates, duplicate passenger-journey detection, and stop-to-shape alignment. These remain generic source-consistency checks rather than rules tied to a particular route or incident.

## Privacy and safety

- The server binds to `127.0.0.1` only.
- It makes no outbound requests and uses no telemetry or CDN assets.
- Audit inputs are local paths. The advanced viewer opens a user-selected ZIP
  directly in browser memory; neither mode sends feed data off the workstation.
- ZIP paths are screened before any system extraction test.
- The application has no third-party Python dependencies.
