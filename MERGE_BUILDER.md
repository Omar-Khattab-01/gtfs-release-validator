# Build a local GTFS merge candidate

`merge_gtfs.py` creates a new GTFS ZIP from CleverCAD, HASTUS bus and optional
HASTUS rail. It runs locally with Python 3.10 or later and the standard library.
Java and MobilityData are not needed to build a candidate. The final vendor ZIP
is **not an input to the generation algorithm**.

This is an experimental reconstruction of the October 16 merge, not the vendor's
software. Every output is marked `DRAFT_NOT_APPROVED` in its companion report.
Matching a historical release establishes that release's reproducibility; it
does not establish the correct agency policy for every future release.

## Windows interface (recommended)

1. Open **`start_windows.bat`**, as you do for validation.
2. Click **Build merged GTFS** at the top of the website.
3. Browse for the required CleverCAD and HASTUS bus ZIPs. Add the separate
   HASTUS rail ZIP for a complete agency feed. **Use inspector paths** reuses
   the paths already entered in the inspection form.
4. Choose the first/last service dates and a save folder. Leave the ZIP filename
   blank for a unique name, or enter a new `.zip` filename.
5. Press **Build draft GTFS**. Keep the server's command window open while it
   reads, matches, builds and verifies the feed. Large exports take several minutes.

The page shows route/trip/stop counts, grouped review items, core validation and
archive checks. Download the generated ZIP, full receipt/crosswalk and review CSV.
**Use in inspector** fills the existing inspection form with the sources and
generated final; choose your validation options and press **Validate & inspect**.

Under **Optional comparison and custom settings**, you can select a reference
final for an independent comparison, a custom policy JSON or a route-sort CSV.
Reference differences do not remove the generated draft. Failed comparisons
are displayed separately and leave the draft and receipt available.

**Recent builds** recovers completed results after restarting. Build history is
stored in `%LOCALAPPDATA%\GTFS Merge Auditor\build-history`, separately from the
index cache. The default output folder is `merged-exports` alongside it. Original
outputs remain in the selected save folder; browser downloads are additional
copies. Moving/deleting outputs outside the app makes those downloads unavailable.
If the server stops mid-build, history marks the build interrupted rather than
claiming it finished. Only one merge runs at a time within the local server.

Browse uses Python's native Tk file dialog on the server's computer. If that
component is unavailable in a restricted Python installation, paste the full path;
quoted and unquoted Windows paths both work. No browser file uploads are needed.
The page remembers its form fields in local browser storage when available.

## Windows command (alternative)

Open a command prompt in this project folder. Choose a new output filename and
the intended publication window, expressed as GTFS service dates:

```bat
build_windows.bat ^
  --cad "C:\GTFS\CW.zip" ^
  --hastus "C:\GTFS\HASTUS-BUS.zip" ^
  --rail "C:\GTFS\HASTUS-RAIL.zip" ^
  --start-date 20261016 ^
  --end-date 20261116 ^
  --output "C:\GTFS\results\candidate-20261016.zip" ^
  --allow-draft
```

In PowerShell, use a single line:

```powershell
py -3 merge_gtfs.py --cad "C:\GTFS\CW.zip" --hastus "C:\GTFS\HASTUS-BUS.zip" --rail "C:\GTFS\HASTUS-RAIL.zip" --start-date 20261016 --end-date 20261116 --output "C:\GTFS\results\candidate-20261016.zip" --allow-draft
```

Omit `--rail` for a bus-only candidate; its report flags that rail was not
supplied. Use `python` instead of `py -3` when the Windows Python launcher is
unavailable. `build_windows.bat` selects whichever is available. Runtime files,
temporary comparison databases and output files stay on the local computer.

`--allow-draft` permits a local artifact with review items. Without it, unresolved
joins, omitted nonempty tables or core validation errors stop the build. It does
not bypass missing referenced shapes, ambiguous stop-code mappings, namespace
collisions or overwrite protections.

## What the reconstructed merge does

| Data | Rule |
| --- | --- |
| Bus trip/route/service/shape IDs | Retain CAD IDs. |
| Bus calls and schedule | Retain CAD stop order, arrival/departure times, drop-off rules, timing points and distances. `24:00:00` remains on its original service day. |
| Bus destinations and availability | Use HASTUS trip headsign, wheelchair and bicycle values when all supported candidates agree. Otherwise retain CAD and report the conflict. |
| Bus boarding/destination by stop | Use HASTUS pickup values and stop headsigns at aligned occurrences when candidates agree. Otherwise retain CAD pickup and a blank stop headsign, with conflicts reported. |
| Stop mapping | Match HASTUS `stop_id` to a unique CAD `stop_code`. Duplicate CAD codes stop the build. |
| Bus stop definitions | Use HASTUS names/station/platform metadata with CAD coordinates. Retain source stations and CAD-only stops used by published trips. Unmapped HASTUS non-station definitions are excluded and counted. |
| Routes | Use HASTUS metadata with CAD bus route IDs and the bundled agency sort-order CSV. |
| Shapes | Copy referenced CAD bus and HASTUS rail geometry; remove unreferenced geometry. Missing shapes or colliding bus/rail shape IDs stop the build. |
| Rail | Retain rail routes, schedules, services, platform IDs and shapes. Remove only an exact `-service_id` suffix from rail trip IDs. Missing rail stop-time distances become the observed `0` placeholder, not a calculated distance. |
| Dates and feed metadata | Clip CAD/rail calendars and exceptions to the explicitly supplied window. Use HASTUS publisher metadata and CAD feed version. |
| Publication exclusions | Apply the visible JSON agency policy described below. |

Trip matching uses mapped ordered stops, operating dates and exact departure
times first. Changed patterns can match on identical first departure and terminal
arrival with at least 90% ordered stop overlap. Another path uses two or more
common timing-point anchors within the configured tolerance (at most 60 seconds),
with at least 80% ordered stop overlap. The 80–90% tier is explicitly a review
item. Independent exact matches may establish a block relationship for a date
only when at least two distinct HASTUS trips agree and there is no conflict.

The algorithm does not select the first plausible candidate. It records candidate
IDs, uncovered dates and ambiguous dates, then applies metadata only by consensus.
Repeated stop visits are aligned by occurrence; ambiguous loop visits retain the
fallback. Identical candidate attributes can support enrichment even when the
precise HASTUS trip ID remains ambiguous. Review the crosswalk before release.

## Agency policy

The default file is `gtfs_validator/release_policy.json`. Copy it to an external
JSON file and pass `--policy "C:\GTFS\agency-policy.json"` when changing rules.
Its complete contents and SHA-256 are recorded in every receipt.

- Route 898 is excluded, as requested for non-revenue service.
- Routes numbered 400–499 keep direction `0`. This reproduces the supplied
  release; confirm the retained direction for a new service period.
- `clear_block_ids` defaults to an empty list, preserving CAD blocks.
- Fare tables are explicitly omitted by this publication profile. A nonempty
  `frequencies.txt` or `transfers.txt` stops the build unless its omission is
  explicitly authorized in the policy. The current builder does not merge them.
- Other unsupported source tables or columns are visible review items. They are
  not represented as supported publication content. `error_warning.txt` is a
  source diagnostic log, not a published GTFS table.

The October 16 reference clears `999-01`, `999-02`, `999-03` and `999-04` on 24
trip records, but retains later `999-xx` blocks. That is an observed difference,
not a proven general placeholder-block rule. A historical replay can set:

```json
"clear_block_ids": ["999-01", "999-02", "999-03", "999-04"]
```

Use this setting only when those specific blocks are intended to be cleared for
the release being built. Do not automatically clear every `999-xx` block.

## Outputs and verification

The builder creates a new ZIP and a same-name `.report.json` containing:

- Source paths and before/after SHA-256 checks; source ZIPs stay read-only.
- Publication window, policy snapshot and route-sort reference hash.
- Included/excluded trip counts, unmatched/ambiguous crosswalks and fallbacks.
- Changed trip and stop-time metadata counts and core validator findings.
- Output hash, ZIP CRC results, root member list and stored/extracted modes.

All nine core tables are written at ZIP root. Every member is explicitly stored
as a Unix regular file with mode `0644`; output is extracted and checked too.
On Windows, NTFS permissions are separate from Unix mode bits, so stored ZIP
metadata is verified while extracted POSIX permission enforcement is reported as
platform dependent. Inputs, existing outputs and receipts are never overwritten.

To compare with a known final **after generation**, append:

```bat
--reference "C:\GTFS\KNOWN-FINAL.zip"
```

Or compare an existing candidate independently:

```powershell
py -3 -m gtfs_validator compare-releases "C:\GTFS\candidate.zip" "C:\GTFS\KNOWN-FINAL.zip" --output "C:\GTFS\comparison.json"
```

This checks member names, record keys and every field. It normalizes surrounding
whitespace and numeric formatting, so equivalence means equal keyed GTFS data,
not byte-identical ZIPs or CSV ordering. Duplicate record keys are rejected.
Comparison uses a temporary disk database rather than loading millions of full
rows into memory; allow several minutes and temporary disk space for a large
feed. Generation still indexes the schedules in memory and is a batch operation.

Builder exit code `0` means the requested draft artifacts were created and any
requested reference comparison passed. Code `2` means build failure or reference
differences. If comparison differs, the generated ZIP and reports remain for
investigation. Neither code means agency approval. Inspect the candidate in the
existing local UI and run MobilityData separately before publishing.

The new builder has automated Python coverage and was exercised on the supplied
full-size archives on macOS. The Windows launcher uses portable Python APIs but
has not yet been exercised on a Windows workstation. No network, upload or
automatic publication is part of this command.
