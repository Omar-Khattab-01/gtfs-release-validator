from __future__ import annotations

import csv
import io
import json
import mimetypes
import threading
import uuid
import webbrowser
import zipfile
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .details import build_detail
from .merge import validate_merge
from .engine import validate_feed
from . import viewer


PACKAGE_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PACKAGE_ROOT / "web_assets"
MAX_REQUEST_BYTES = 64 * 1024


@dataclass
class Job:
    id: str
    clevercad_path: str
    hastus_path: str
    final_path: str = ""
    status: str = "queued"
    error: str | None = None
    report: dict[str, Any] | None = None
    details_cache: dict[int, dict[str, Any]] = field(default_factory=dict)
    variation_cache: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    viewer_cache: dict[tuple, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def public(self) -> dict[str, Any]:
        with self.lock:
            payload: dict[str, Any] = {
                "id": self.id,
                "clevercad_path": self.clevercad_path,
                "hastus_path": self.hastus_path,
                "final_path": self.final_path,
                "status": self.status,
                "error": self.error,
            }
            if self.report is not None:
                payload["report"] = self.report
            return payload


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def _run_job(job: Job) -> None:
    with job.lock:
        job.status = "running"
    try:
        report = validate_merge(job.clevercad_path, job.hastus_path, job.final_path) if job.clevercad_path and job.hastus_path else validate_feed(job.final_path)
        if not job.clevercad_path and not job.hastus_path:
            report.stats["inputs"] = {"Final merged GTFS": {"path": job.final_path, "sha256": report.sha256}}
        with job.lock:
            job.report = report.to_dict()
            job.status = "complete"
    except Exception as exc:  # Last-resort isolation for the web worker.
        with job.lock:
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "failed"


def _find_job(job_id: str) -> Job | None:
    with JOBS_LOCK:
        return JOBS.get(job_id)


class ValidatorHandler(BaseHTTPRequestHandler):
    server_version = "GTFSValidator/0.8.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def _security_headers(self, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self' blob:; frame-ancestors 'none'",
        )

    def _bytes(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self._security_headers(content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status: int, payload: Any) -> None:
        self._bytes(
            status,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/":
            return self._serve_asset("index.html")
        if path.startswith("/file-viewer/"):
            relative = path.removeprefix("/file-viewer/") or "index.html"
            root = (WEB_ROOT / "file_viewer").resolve()
            asset = (root / relative).resolve()
            if not asset.is_relative_to(root) or not asset.is_file():
                return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            return self._bytes(HTTPStatus.OK, asset.read_bytes(), content_type)
        if path.startswith("/assets/"):
            name = path.removeprefix("/assets/")
            if "/" in name or "\\" in name or name.startswith("."):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return self._serve_asset(name)

        parts = [part for part in path.split("/") if part]
        if len(parts) >= 3 and parts[:2] == ["api", "runs"]:
            job = _find_job(parts[2])
            if job is None:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown run"})
            if len(parts) == 3:
                return self._json(HTTPStatus.OK, job.public())
            if len(parts) == 4 and parts[3] == "viewer":
                query = parse_qs(parsed_url.query)
                get = lambda key, default="": str((query.get(key) or [default])[0])
                source = get("source", "final")
                feed_path = {"cad": job.clevercad_path, "hastus": job.hastus_path, "final": job.final_path}.get(source)
                if not feed_path:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": "This source was not supplied"})
                key = (source, get("route_id"), get("trip_id"), get("table"), get("offset", "0"))
                try:
                    with job.lock:
                        data = job.viewer_cache.get(key)
                    if data is None:
                        if get("trip_id"):
                            data = viewer.trip_detail(feed_path, get("trip_id"))
                        elif get("route_id"):
                            data = viewer.route_detail(feed_path, get("route_id"))
                        elif get("table"):
                            data = viewer.table_page(feed_path, get("table"), max(0, int(get("offset", "0"))))
                        else:
                            data = viewer.inventory(feed_path)
                        with job.lock:
                            job.viewer_cache[key] = data
                    return self._json(HTTPStatus.OK, data)
                except (OSError, KeyError, ValueError, UnicodeDecodeError, csv.Error, zipfile.BadZipFile) as exc:
                    return self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": f"Could not inspect feed: {exc}"})
            if len(parts) == 4 and parts[3] == "report.json":
                payload = job.public()
                if payload.get("report") is None:
                    return self._json(HTTPStatus.CONFLICT, {"error": "Report is not ready"})
                content = json.dumps(payload["report"], ensure_ascii=False, indent=2).encode("utf-8")
                return self._download(content, f"gtfs-validation-{job.id}.json", "application/json; charset=utf-8")
            if len(parts) == 4 and parts[3] == "findings.csv":
                payload = job.public()
                if payload.get("report") is None:
                    return self._json(HTTPStatus.CONFLICT, {"error": "Report is not ready"})
                return self._download_csv(payload["report"], job.id)
            if len(parts) == 5 and parts[3] == "details":
                try:
                    finding_index = int(parts[4])
                except ValueError:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid finding index"})
                payload = job.public()
                report = payload.get("report")
                if report is None:
                    return self._json(HTTPStatus.CONFLICT, {"error": "Report is not ready"})
                findings = report.get("findings", [])
                if finding_index < 0 or finding_index >= len(findings):
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown finding"})
                with job.lock:
                    cached = job.details_cache.get(finding_index)
                if cached is None:
                    try:
                        finding = dict(findings[finding_index])
                        context = dict(finding.get("context") or {})
                        if job.final_path and finding.get("rule_id") in {"TRP102", "TRP103"}:
                            route = next((item for item in report.get("stats", {}).get("trip_reconciliation", {}).get("route_health", []) if item["route_short_name"] == context.get("route_short_name")), {})
                            pair = next((item for item in route.get("variation_pairs", []) if item["clevercad_variation_id"] == context.get("clevercad_variation_id") and item["hastus_variation_id"] == context.get("hastus_variation_id")), {})
                            if pair.get("final_matches"):
                                context["final_trip_id"] = pair["final_matches"][0]["example_trip_id"]
                        finding["context"] = context
                        cached = build_detail(
                            finding,
                            job.clevercad_path,
                            job.hastus_path,
                            job.final_path,
                        )
                    except (OSError, KeyError, UnicodeDecodeError, csv.Error, zipfile.BadZipFile) as exc:
                        return self._json(
                            HTTPStatus.UNPROCESSABLE_ENTITY,
                            {"error": f"Could not load detail evidence: {exc}"},
                        )
                    with job.lock:
                        job.details_cache[finding_index] = cached
                return self._json(HTTPStatus.OK, cached)
            if len(parts) == 4 and parts[3] == "variation-detail":
                query = parse_qs(parsed_url.query)
                cad_trip_id = str((query.get("cad_trip_id") or [""])[0]).strip()
                hastus_trip_id = str((query.get("hastus_trip_id") or [""])[0]).strip()
                final_trip_id = str((query.get("final_trip_id") or [""])[0]).strip()
                if not cad_trip_id and not hastus_trip_id:
                    return self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "At least one source representative trip ID is required"},
                    )
                cache_key = (cad_trip_id, hastus_trip_id, final_trip_id)
                with job.lock:
                    cached = job.variation_cache.get(cache_key)
                if cached is None:
                    try:
                        cached = build_detail(
                            {
                                "rule_id": "TRP102",
                                "context": {
                                    "clevercad_trip_id": cad_trip_id,
                                    "hastus_trip_id": hastus_trip_id,
                                    "final_trip_id": final_trip_id,
                                },
                            },
                            job.clevercad_path,
                            job.hastus_path,
                            job.final_path,
                        )
                    except (OSError, KeyError, UnicodeDecodeError, csv.Error, zipfile.BadZipFile) as exc:
                        return self._json(
                            HTTPStatus.UNPROCESSABLE_ENTITY,
                            {"error": f"Could not load variation evidence: {exc}"},
                        )
                    with job.lock:
                        job.variation_cache[cache_key] = cached
                return self._json(HTTPStatus.OK, cached)
        return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/runs":
            return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        if self.headers.get("X-GTFS-Validator") != "1":
            return self._json(HTTPStatus.FORBIDDEN, {"error": "Missing local request header"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Invalid request size"})
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
        clevercad_path = str(payload.get("clevercad_path", "")).strip()
        hastus_path = str(payload.get("hastus_path", "")).strip()
        final_path = str(payload.get("final_path", "")).strip()
        if bool(clevercad_path) != bool(hastus_path) or (not clevercad_path and not final_path):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "Supply both sources, or only a final GTFS ZIP to validate and inspect it"})

        job = Job(
            id=uuid.uuid4().hex[:12],
            clevercad_path=clevercad_path,
            hastus_path=hastus_path,
            final_path=final_path,
        )
        with JOBS_LOCK:
            JOBS[job.id] = job
        worker = threading.Thread(target=_run_job, args=(job,), daemon=True)
        worker.start()
        return self._json(HTTPStatus.ACCEPTED, {"id": job.id, "status": job.status})

    def _serve_asset(self, name: str) -> None:
        path = WEB_ROOT / name
        if not path.is_file():
            return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._bytes(HTTPStatus.OK, path.read_bytes(), content_type)

    def _download(self, content: bytes, filename: str, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self._security_headers(content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _download_csv(self, report: dict[str, Any], job_id: str) -> None:
        output = io.StringIO(newline="")
        columns = [
            "rule_id", "severity", "category", "title", "message", "file", "row",
            "key", "observed", "expected", "context",
        ]
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for finding in report.get("findings", []):
            row = {column: finding.get(column, "") for column in columns}
            row["context"] = json.dumps(row["context"], ensure_ascii=False, sort_keys=True)
            writer.writerow(row)
        self._download(
            output.getvalue().encode("utf-8-sig"),
            f"gtfs-findings-{job_id}.csv",
            "text/csv; charset=utf-8",
        )


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    server = ThreadingHTTPServer((host, port), ValidatorHandler)
    print(f"GTFS Validator is available at http://{host}:{port}")
    print("Press Ctrl+C to stop. Files stay on this computer.")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(f"http://{host}:{port}",)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
