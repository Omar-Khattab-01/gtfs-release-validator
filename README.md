# OC Transpo GTFS Release Validator

This is the first working phase of the offline GTFS release validator. It reads candidate ZIPs without modifying them and runs entirely on the local computer.

## Start the web interface

```bash
cd /Users/omarkhattab/Desktop/CIS/gtfs_validator
python3 -m gtfs_validator serve
```

Then open <http://127.0.0.1:8765>. On macOS, `start.command` can also be opened directly after its executable bit has been set.

The browser asks for a full local ZIP path instead of uploading the archive. This avoids making a second in-memory copy of very large `stop_times.txt` files.

## Command-line validation

```bash
python3 -m gtfs_validator validate /path/to/GTFSExport.zip --output report.json
```

Exit codes are `0` for eligible, `1` for needs review, and `2` for blocked.

## Current coverage

- ZIP CRC, duplicate members, unsafe/nested paths, encryption, special files, compression limits, root layout, stored permissions, and system-extracted permissions
- required files and columns, UTF-8/CSV shape, empty tables, primary keys, and selected GTFS enumerations
- route/trip/service/shape/stop and parent-station relationships
- stop coordinates and route colours
- stop-time syntax (including post-midnight hours), arrival/departure order, unique sequences, and nondecreasing trip times
- orphan shapes
- OC Transpo Route 19 Parliament-bound first-stop rule (`10017`, not `10014`)
- searchable HTML findings plus JSON and CSV report downloads

Baseline comparison, full CleverCAD/HASTUS reconciliation, calendar expansion, duplicate passenger-journey detection, and geospatial stop-to-shape checks remain planned phases.

## Privacy and safety

- The server binds to `127.0.0.1` by default.
- It makes no outbound requests and uses no CDN assets or telemetry.
- Candidate ZIPs are treated as read-only.
- ZIP paths are screened before any system extraction test.
- The application has no third-party Python dependencies.
