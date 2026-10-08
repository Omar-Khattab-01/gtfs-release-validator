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

## Windows setup and launch

Requirements: Windows 10/11 and Python 3.10 or newer from <https://www.python.org/downloads/windows/>. During Python installation, enable **Add Python to PATH** and install the Python launcher.

Double-click:

```text
start_windows.bat
```

The launcher checks the Python version, starts the local server, and opens <http://127.0.0.1:8765> in the default browser. Keep the command window open while using the tool. Press `Ctrl+C` to stop it.

No third-party Python packages or internet connection are required.

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

The tool does not contain route- or incident-specific production rules. Previous incidents are represented as test cases for general rules. CleverCAD and HASTUS are the only required inputs.

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
- stored and system-extracted `0644` permissions
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
