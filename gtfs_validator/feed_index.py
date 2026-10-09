"""Optional persistent, disk-backed indexes for read-only GTFS browsing.

ZIP members are streamed once into a private temporary SQLite database. Keeping
the large tables on disk avoids a Python dictionary for every stop-time row.
"""
from __future__ import annotations

import csv
import io
import json
import hashlib
import os
import shutil
import sqlite3
import tempfile
import threading
import weakref
import zipfile
from collections import OrderedDict
from contextlib import closing
from pathlib import Path

from .archive import MAX_MEMBER_BYTES, MAX_TOTAL_BYTES, is_unsafe_name
from . import cache_store


class FeedIndex:
    def __init__(self, path: str, workdir: Path | None = None):
        self.path = path
        self._temp = tempfile.TemporaryDirectory(prefix="gtfs-browse-", dir=workdir)
        self._cleanup = weakref.finalize(self, self._temp.cleanup)
        self.database = Path(self._temp.name) / "feed.sqlite"
        self.columns: dict[str, list[str]] = {}
        self.files: list[dict] = []
        self.small_tables: dict[str, list[dict]] = {}
        self.cache_status = "Session only"
        self.cache_warning = ""
        self._build()

    def _build(self) -> None:
        with closing(sqlite3.connect(self.database)) as db, zipfile.ZipFile(self.path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if sum(item.file_size for item in members) > MAX_TOTAL_BYTES:
                raise ValueError("Feed exceeds the browsing size limit")
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
            db.execute("CREATE TABLE records (name TEXT, row_number INTEGER, entity TEXT, parent TEXT, data TEXT, PRIMARY KEY(name, row_number)) WITHOUT ROWID")
            for item in members:
                self.files.append({"name": item.filename, "bytes": item.file_size})
                if not item.filename.endswith(".txt") or is_unsafe_name(item.filename):
                    continue
                if item.file_size > MAX_MEMBER_BYTES:
                    raise ValueError("GTFS table exceeds the browsing size limit")
                entity_field, parent_field = {
                    "stops.txt": ("stop_id", ""),
                    "trips.txt": ("trip_id", "route_id"),
                    "stop_times.txt": ("", "trip_id"),
                    "shapes.txt": ("", "shape_id"),
                }.get(item.filename, ("", ""))
                with archive.open(item) as raw:
                    reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
                    self.columns[item.filename] = reader.fieldnames or []
                    batch = []
                    for number, row in enumerate(reader):
                        clean = {str(key).strip(): str(value or "").strip() for key, value in row.items()}
                        batch.append((item.filename, number, clean.get(entity_field, ""), clean.get(parent_field, ""), json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
                        if len(batch) == 4000:
                            db.executemany("INSERT INTO records VALUES (?,?,?,?,?)", batch)
                            batch.clear()
                    if batch:
                        db.executemany("INSERT INTO records VALUES (?,?,?,?,?)", batch)
            db.execute("CREATE INDEX records_entity ON records(name, entity) WHERE entity != ''")
            db.execute("CREATE INDEX records_parent ON records(name, parent) WHERE parent != ''")
            db.execute("CREATE TABLE metadata (data TEXT)")
            db.execute("INSERT INTO metadata VALUES (?)", (json.dumps({"schema": cache_store.SCHEMA_VERSION, "columns": self.columns, "files": self.files}),))
            db.commit()
            # Only these small dimension tables are retained in memory.
            for name in ("routes.txt", "stops.txt", "trips.txt"):
                if name in self.columns:
                    self.small_tables[name] = [{str(key).strip(): str(value or "").strip() for key, value in row.items()} for row in self.rows(name)]
        self.stops = {row.get("stop_id", "").strip(): row for row in self.small_tables.get("stops.txt", [])}
        self.trip_ids = {row.get("trip_id", "").strip() for row in self.small_tables.get("trips.txt", [])}

    @classmethod
    def reopen(cls, path: str, database: Path) -> "FeedIndex":
        instance = cls.__new__(cls)
        instance.path, instance.database = path, database
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            metadata = json.loads(db.execute("SELECT data FROM metadata").fetchone()[0])
            if metadata["schema"] != cache_store.SCHEMA_VERSION:
                raise ValueError("Outdated index schema")
            db.execute("SELECT row_number FROM records LIMIT 1").fetchone()
        instance.columns, instance.files = metadata["columns"], metadata["files"]
        instance.small_tables = {}
        for name in ("routes.txt", "stops.txt", "trips.txt"):
            if name in instance.columns:
                instance.small_tables[name] = [{str(k).strip(): str(v or "").strip() for k, v in row.items()} for row in instance.rows(name)]
        instance.stops = {row.get("stop_id", ""): row for row in instance.small_tables.get("stops.txt", [])}
        instance.trip_ids = {row.get("trip_id", "") for row in instance.small_tables.get("trips.txt", [])}
        instance.cache_status, instance.cache_warning = "Reused saved index", ""
        os.utime(database, None)
        return instance

    def _query(self, sql: str, parameters: tuple) -> list[dict]:
        # A separate read-only connection per request works with HTTP threads on Windows.
        with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)) as db:
            return [json.loads(row[0]) for row in db.execute(sql, parameters)]

    def rows(self, name: str) -> list[dict]:
        if name not in self.columns:
            raise KeyError(name)
        if name in self.small_tables:
            return self.small_tables[name]
        return self._query("SELECT data FROM records WHERE name=? ORDER BY row_number", (name,))

    def lookup(self, name: str, key: str, *, entity: bool = False) -> list[dict]:
        if name not in self.columns:
            raise KeyError(name)
        column = "entity" if entity else "parent"
        return self._query(f"SELECT data FROM records INDEXED BY records_{column} WHERE name=? AND {column}=? AND {column} != '' ORDER BY row_number", (name, key))

    def page(self, name: str, offset: int, limit: int) -> dict:
        if name not in self.columns:
            raise ValueError("Unknown GTFS table")
        rows = self._query("SELECT data FROM records WHERE name=? AND row_number>=? ORDER BY row_number LIMIT ?", (name, offset, limit + 1))
        return {"columns": self.columns[name], "rows": rows[:limit], "offset": offset, "has_more": len(rows) > limit}

    def lookup_many(self, name: str, keys: list[str]) -> list[dict]:
        if name not in self.columns:
            raise KeyError(name)
        result = []
        with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)) as db:
            for start in range(0, len(keys), 400):
                chunk = keys[start:start + 400]
                placeholders = ",".join("?" for _ in chunk)
                sql = f"SELECT data FROM records INDEXED BY records_parent WHERE name=? AND parent IN ({placeholders}) AND parent != '' ORDER BY row_number"
                result.extend(json.loads(row[0]) for row in db.execute(sql, (name, *chunk)))
        return result

    def batches(self, name: str, size: int = 25000):
        if name not in self.columns:
            raise KeyError(name)
        with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)) as db:
            cursor = db.execute("SELECT data FROM records WHERE name=? ORDER BY row_number", (name,))
            while rows := cursor.fetchmany(size):
                yield [json.loads(row[0]) for row in rows]


_indexes: OrderedDict[tuple, FeedIndex] = OrderedDict()
_lock = threading.Lock()
_live = weakref.WeakSet()
MAX_CACHED_FEEDS = 6


def get_index(path: str, *, persist: bool = False) -> FeedIndex:
    resolved = Path(path).resolve()
    stat = resolved.stat()
    key = (str(resolved), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    # Serialize first builds: concurrent clicks must not import the same ZIP twice.
    with _lock:
        index = _indexes.get(key)
        if index is None or (persist and index.cache_status == "Session only"):
            destination = None
            warning = ""
            if persist:
                try:
                    root = cache_store.cache_root()
                    root.mkdir(parents=True, exist_ok=True, mode=0o700)
                    digest = hashlib.sha256()
                    with resolved.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                    destination = root / f"index-v2-{digest.hexdigest()}.sqlite"
                    if index is None and destination.is_file() and not destination.is_symlink():
                        try:
                            index = FeedIndex.reopen(str(resolved), destination)
                        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                            index = None  # An interrupted/corrupt cache is rebuilt, never trusted.
                except OSError as exc:
                    warning = f"Could not save index: {exc}"
            new_session = index is None
            if new_session:
                try:
                    index = FeedIndex(str(resolved), destination.parent if destination else None)
                except OSError as exc:
                    if destination is None:
                        raise
                    destination = None
                    warning = f"Could not save index: {exc}"
                    index = FeedIndex(str(resolved))
            after = resolved.stat()
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != key[1:]:
                raise ValueError("Feed changed during indexing; rerun the audit")
            if destination and index.cache_status == "Session only":
                active = {item.database for item in _live}
                size = index.database.stat().st_size
                result = cache_store.prune(active, reserve=size)
                if result["bytes"] + size <= cache_store.MAX_BYTES:
                    try:
                        # Copy before publication: existing HTTP readers may still use
                        # the session file, including on Windows.
                        with tempfile.TemporaryDirectory(prefix="publish-", dir=destination.parent) as staging:
                            staged = Path(staging) / "feed.sqlite"
                            shutil.copyfile(index.database, staged)
                            os.replace(staged, destination)
                        index.database = destination
                        index.cache_status = "Saved for future sessions"
                        if new_session:
                            index._cleanup()
                    except OSError as exc:
                        warning = f"Could not save index: {exc}"
                else:
                    warning = "Index exceeds the 10 GB cache budget; using session-only browsing."
            index.cache_warning = warning
            _indexes[key] = index
            _live.add(index)
            while len(_indexes) > MAX_CACHED_FEEDS:
                _indexes.popitem(last=False)
        _indexes.move_to_end(key)
        return index


def cache_info(remove_unused: bool = False) -> dict:
    with _lock:
        active = {item.database for item in _live}
        cleanup = cache_store.prune(active, remove_all=True) if remove_unused else None
        items = cache_store.entries()
        return {"directory": str(cache_store.cache_root()), "entries": items,
                "bytes": sum(item["bytes"] for item in items), "limit_bytes": cache_store.MAX_BYTES,
                "retention_days": 30, "cleanup": cleanup}


def clear_indexes() -> None:
    """Release session cache; in-flight readers keep their own index reference."""
    with _lock:
        _indexes.clear()
