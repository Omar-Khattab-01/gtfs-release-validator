"""Managed per-user cache. Only this application's named index files are removed."""
import os
import re
import time
from pathlib import Path

SCHEMA_VERSION = 2
MAX_BYTES = 10 * 1024**3
MAX_AGE_SECONDS = 30 * 86400
NAME = re.compile(r"(?:index-v2-[0-9a-f]{64}\.sqlite|audit-v1-[0-9a-f]{64}\.json)$")


def cache_root() -> Path:
    custom = os.environ.get("GTFS_VALIDATOR_CACHE_DIR")
    if custom:
        return Path(custom).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")))
    return base / "GTFS Merge Auditor" / "cache"


def entries() -> list[dict]:
    root = cache_root()
    if not root.exists():
        return []
    return [{"name": path.name, "bytes": path.stat().st_size, "last_used": path.stat().st_mtime}
            for path in root.iterdir() if NAME.fullmatch(path.name) and path.is_file() and not path.is_symlink()]


def prune(active: set[Path], *, remove_all: bool = False, reserve: int = 0) -> dict:
    items = sorted(entries(), key=lambda item: item["last_used"])
    total = sum(item["bytes"] for item in items)
    removed, skipped = [], []
    for item in items:
        path = cache_root() / item["name"]
        if not (remove_all or time.time() - item["last_used"] > MAX_AGE_SECONDS or total + reserve > MAX_BYTES):
            continue
        if path in active:
            skipped.append(item["name"])
            continue
        try:
            path.unlink()
            total -= item["bytes"]
            removed.append(item["name"])
        except OSError:
            skipped.append(item["name"])
    return {"removed": removed, "skipped": skipped, "bytes": total}
