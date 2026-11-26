from __future__ import annotations

import hashlib
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .models import ValidationReport


REQUIRED_FILES = {
    "agency.txt",
    "routes.txt",
    "stops.txt",
    "trips.txt",
    "stop_times.txt",
}
AGENCY_EXPECTED_FILES = {"feed_info.txt", "shapes.txt"}
MAX_MEMBER_BYTES = 4 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 250


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_unsafe_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        not name
        or normalized.startswith("/")
        or "\\" in name
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(path.parts) != 1
        or ":" in path.parts[0]
    )


def inspect_archive(path: Path, report: ValidationReport) -> zipfile.ZipFile | None:
    report.archive_size = path.stat().st_size
    report.sha256 = sha256_file(path)
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        report.add(
            "PKG001",
            "blocker",
            "Packaging",
            "Archive cannot be opened",
            f"The candidate is not a readable ZIP archive: {exc}",
        )
        return None

    infos = archive.infolist()
    names = [info.filename for info in infos]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    for name in duplicates:
        report.add(
            "PKG002",
            "blocker",
            "Packaging",
            "Duplicate archive member",
            f"The ZIP contains more than one entry named {name!r}.",
            file=name,
        )

    total_uncompressed = 0
    unspecified_permissions = []
    for info in infos:
        name = info.filename
        total_uncompressed += info.file_size
        if is_unsafe_name(name):
            report.add(
                "PKG003",
                "blocker",
                "Packaging",
                "Unsafe or nested archive path",
                "GTFS members must be regular files at the ZIP root.",
                file=name,
                observed=name,
                expected="root-level filename",
            )
        if info.is_dir():
            report.add(
                "PKG004",
                "error",
                "Packaging",
                "Directory entry in GTFS archive",
                "The release archive should contain root-level GTFS files only.",
                file=name,
            )
        if info.flag_bits & 0x1:
            report.add(
                "PKG005",
                "blocker",
                "Packaging",
                "Encrypted archive member",
                "Encrypted GTFS members cannot be safely validated or consumed.",
                file=name,
            )
        if info.file_size > MAX_MEMBER_BYTES:
            report.add(
                "PKG006",
                "blocker",
                "Packaging",
                "Archive member exceeds safety limit",
                f"Uncompressed size is {info.file_size:,} bytes.",
                file=name,
                expected=f"at most {MAX_MEMBER_BYTES:,} bytes",
            )
        ratio = info.file_size / max(info.compress_size, 1)
        if ratio > MAX_COMPRESSION_RATIO and info.file_size > 10 * 1024 * 1024:
            report.add(
                "PKG007",
                "blocker",
                "Packaging",
                "Suspicious compression ratio",
                f"Compression ratio is {ratio:.1f}:1.",
                file=name,
                expected=f"at most {MAX_COMPRESSION_RATIO}:1",
            )

        stored_mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(stored_mode)
        permissions = stat.S_IMODE(stored_mode)
        if file_type and file_type != stat.S_IFREG:
            report.add(
                "PKG008",
                "blocker",
                "Packaging",
                "Archive member is not a regular file",
                f"Stored Unix mode is {stored_mode:o}.",
                file=name,
            )
        if not info.is_dir() and info.create_system != 3 and stored_mode == 0:
            unspecified_permissions.append(name)
        elif not info.is_dir() and permissions == 0o600:
            report.add(
                "PKG009",
                "blocker",
                "Packaging",
                "Stored file mode is 0600",
                "This ZIP member stores mode 0600. Review it before publication.",
                file=name,
                observed=f"{permissions:03o}",
                expected="stored mode other than 0600",
            )

        report.files[name] = {
            "compressed_bytes": info.compress_size,
            "uncompressed_bytes": info.file_size,
            "crc32": f"{info.CRC:08x}",
            "stored_mode": None if name in unspecified_permissions else f"{permissions:03o}",
        }

    if total_uncompressed > MAX_TOTAL_BYTES:
        report.add(
            "PKG010",
            "blocker",
            "Packaging",
            "Archive exceeds total safety limit",
            f"Total uncompressed size is {total_uncompressed:,} bytes.",
            expected=f"at most {MAX_TOTAL_BYTES:,} bytes",
        )

    bad_member = archive.testzip()
    if bad_member:
        report.add(
            "PKG011",
            "blocker",
            "Packaging",
            "ZIP integrity test failed",
            "CRC validation failed for this member.",
            file=bad_member,
        )

    name_set = set(names)
    for unexpected in sorted(name for name in name_set if not name.endswith(".txt")):
        report.add(
            "PKG017",
            "warning",
            "Packaging",
            "Unexpected non-GTFS member",
            "The release profile expects root-level GTFS .txt files only.",
            file=unexpected,
        )
    for required in sorted(REQUIRED_FILES - name_set):
        report.add(
            "PKG012",
            "blocker",
            "Packaging",
            "Required GTFS file is missing",
            f"{required} is required for this feed profile.",
            file=required,
        )
    if not ({"calendar.txt", "calendar_dates.txt"} & name_set):
        report.add(
            "PKG013",
            "blocker",
            "Packaging",
            "Service calendar is missing",
            "At least one of calendar.txt or calendar_dates.txt is required.",
        )
    for expected in sorted(AGENCY_EXPECTED_FILES - name_set):
        report.add(
            "PKG014",
            "info" if report.profile == 'source-inspection' else "error",
            "Packaging",
            "Optional source file not supplied" if report.profile == 'source-inspection' else "Expected agency file is missing",
            f"{expected} is checked when supplied; publication expectations apply to the final feed." if report.profile == 'source-inspection' else f"{expected} is expected in the OC Transpo release profile.",
            file=expected,
        )

    # Extraction is available in Packaging on demand, rather than decompressing
    # every feed again during each technical validation.
    return archive
