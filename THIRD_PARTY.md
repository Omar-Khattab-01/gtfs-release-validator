# Bundled GTFS Viewer

The local file viewer at `/file-viewer/` is built from Omar Khattab's
https://github.com/Omar-Khattab-01/gtfs-viewer repository, main branch checked
out on October 8, 2026, commit `4b55f077648bab942059e138ba93544816b2671f`.
It is integrated at the repository owner's request.
The original source remains in that repository; this project distributes its
generated static assets. These assets run entirely on the local device.

Build: `npm ci --ignore-scripts` then
`npm run build -- --base=/file-viewer/`. Copy `pages-dist/` into
`gtfs_validator/web_assets/file_viewer/`.

The viewer includes React (MIT), JSZip (MIT), and Papa Parse (MIT).
Upstream license notices are included alongside the generated assets.

# Local validation engines

The agency profile in `gtfs_validator/agency_source.py` is adapted from the
Python validator supplied by the repository owner on October 9, 2026. Its route
sort-order reference was supplied by the owner. Agency-specific policy and
known exceptions are displayed separately from GTFS specification checks.

MobilityData's canonical GTFS validator is optional and downloaded from
https://github.com/MobilityData/gtfs-validator using its official release assets.
The Java JAR is not redistributed in this repository. Its upstream project is
licensed under Apache-2.0. The local adapter was tested with CLI v8.0.1.
