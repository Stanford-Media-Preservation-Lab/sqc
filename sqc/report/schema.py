"""Per-file report data structures shared by both vendor-qc and donor-triage modes."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

TOOL_VERSION = "0.1.0"

# Status ranking — lower index = worse. TOOL_FAILURE is worse than FAIL: it means
# the batch worker itself crashed (subprocess timeout, missing binary, unexpected
# exception) rather than the file genuinely failing a check, so it must never be
# treated as a completed/resumable result (see report/writer.py's resume check).
STATUS_ORDER = {"TOOL_FAILURE": -1, "FAIL": 0, "WARN": 1, "PASS": 2, "SKIP": 3, "INFO": 4}


def worst(*statuses: str) -> str:
    return min(statuses, key=lambda s: STATUS_ORDER.get(s, 99))


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL | SKIP | INFO
    detail: str
    value: object = None
    pattern_id: Optional[str] = None  # set when this result matches a known pattern

    def __str__(self) -> str:
        v = f" [{self.value}]" if self.value is not None else ""
        p = f" ({self.pattern_id})" if self.pattern_id else ""
        return f"  {self.status:<4}  {self.name}{v}{p}: {self.detail}"


@dataclass
class FrameStats:
    total_frames: int
    expected_duration: float  # seconds (modal packet duration)
    anomalous_count: int
    anomalous_positions: list  # list of (frame_index, duration_s) tuples
    min_duration: float
    max_duration: float
    duration_histogram: dict  # {duration_str: count}
    classification: str  # NONE | SPIN_DOWN | DROPPED_FRAMES | TIMEBASE_ROUNDING
    trim_duration_s: Optional[float] = None


@dataclass
class FileReport:
    path: Path
    mode: str  # "vendor_qc" | "donor_triage"
    profile_name: Optional[str] = None
    file_size: int = 0
    checks: list = field(default_factory=list)
    overall_status: str = "PASS"
    probe_data: dict = field(default_factory=dict)
    mediainfo_data: dict = field(default_factory=dict)
    mediatrace_data: dict = field(default_factory=dict)
    exiftool_data: dict = field(default_factory=dict)
    frame_stats: Optional[FrameStats] = None
    matched_patterns: list = field(default_factory=list)
    error: Optional[str] = None

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)
        self.overall_status = worst(self.overall_status, result.status)
        if result.pattern_id and result.pattern_id not in self.matched_patterns:
            self.matched_patterns.append(result.pattern_id)

    def add_all(self, results: list) -> None:
        for r in results:
            self.add(r)

    @classmethod
    def from_json_dict(cls, data: dict, path: Path) -> "FileReport":
        """Reconstruct enough of a FileReport from a persisted JSON report to
        write a CSV row for a resumed/skipped file. Raw probe/mediainfo/
        mediatrace/exiftool dumps aren't persisted to JSON (see to_json_dict)
        so those fields stay empty here — a resumed file's CSV row will have
        blank codec/resolution columns; its own JSON report has the full detail.
        """
        fs_data = data.get("frame_stats")
        frame_stats = FrameStats(**fs_data) if fs_data else None
        report = cls(
            path=path,
            mode=data.get("mode", ""),
            profile_name=data.get("profile"),
            file_size=data.get("file_size", 0),
            overall_status=data.get("overall_status", "PASS"),
            frame_stats=frame_stats,
            matched_patterns=data.get("matched_patterns", []),
            error=data.get("error"),
        )
        for c in data.get("checks", []):
            report.checks.append(CheckResult(
                name=c["name"], status=c["status"], detail=c["detail"],
                value=c.get("value"), pattern_id=c.get("pattern_id"),
            ))
        return report

    def to_json_dict(self) -> dict:
        return {
            "tool": f"sqc v{TOOL_VERSION}",
            "mode": self.mode,
            "profile": self.profile_name,
            "timestamp": datetime.now().isoformat(),
            "file": str(self.path),
            "file_size": self.file_size,
            "overall_status": self.overall_status,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "detail": c.detail,
                    "value": c.value,
                    "pattern_id": c.pattern_id,
                }
                for c in self.checks
            ],
            "frame_stats": asdict(self.frame_stats) if self.frame_stats else None,
            "matched_patterns": self.matched_patterns,
            "error": self.error,
        }
