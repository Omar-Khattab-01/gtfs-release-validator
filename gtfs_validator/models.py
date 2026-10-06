from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


SEVERITY_ORDER = {"blocker": 0, "error": 1, "warning": 2, "info": 3}


@dataclass(slots=True)
class Finding:
    rule_id: str
    severity: str
    category: str
    title: str
    message: str
    file: str | None = None
    row: int | None = None
    key: str | None = None
    observed: str | None = None
    expected: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationReport:
    source_path: str
    tool_version: str = "0.4.0"
    profile: str = "oc-transpo"
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str | None = None
    sha256: str | None = None
    archive_size: int | None = None
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    suppressed_findings: int = 0
    max_findings: int = 10_000

    def add(
        self,
        rule_id: str,
        severity: str,
        category: str,
        title: str,
        message: str,
        **details: Any,
    ) -> None:
        if len(self.findings) >= self.max_findings:
            self.suppressed_findings += 1
            return
        self.findings.append(
            Finding(
                rule_id=rule_id,
                severity=severity,
                category=category,
                title=title,
                message=message,
                **details,
            )
        )

    @property
    def counts(self) -> dict[str, int]:
        counts = {name: 0 for name in SEVERITY_ORDER}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts

    @property
    def decision(self) -> str:
        counts = self.counts
        if counts["blocker"]:
            return "BLOCKED"
        if counts["error"] or counts["warning"]:
            return "NEEDS REVIEW"
        return "ELIGIBLE FOR APPROVAL"

    def finish(self) -> None:
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.findings.sort(
            key=lambda item: (
                SEVERITY_ORDER.get(item.severity, 99),
                item.rule_id,
                item.file or "",
                item.row or 0,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_version": self.tool_version,
            "profile": self.profile,
            "source_path": self.source_path,
            "sha256": self.sha256,
            "archive_size": self.archive_size,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "decision": self.decision,
            "counts": self.counts,
            "suppressed_findings": self.suppressed_findings,
            "files": self.files,
            "stats": self.stats,
            "findings": [finding.to_dict() for finding in self.findings],
        }
