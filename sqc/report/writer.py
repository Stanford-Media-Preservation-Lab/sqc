"""Per-file JSON report writing and resume-by-JSON-existence logic.

sqc resumes by checking whether a file's JSON report already exists (and
represents a completed run), not by re-scanning log text — see logs.py's
docstring for why this is a deliberate departure from srw/vdg's convention.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from sqc.report.schema import FileReport


def report_path_for(report_dir: Path, source_path: Path) -> Path:
    return report_dir / f"{source_path.stem}_qc.json"


def write_json_report(report: FileReport, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_path_for(report_dir, report.path)
    out.write_text(json.dumps(report.to_json_dict(), indent=2, default=str), encoding="utf-8")
    return out


def load_json_report(report_dir: Path, source_path: Path) -> Optional[dict]:
    p = report_path_for(report_dir, source_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def should_skip_for_resume(report_dir: Path, source_path: Path) -> bool:
    """True if a prior run already produced a usable report for this file.

    A TOOL_FAILURE result is never treated as "done" — a tool crash (timeout,
    transient missing binary) is exactly the kind of failure resume should
    retry, unlike a genuine FAIL verdict (also retried, but because the user
    fixed something and re-ran, not because the previous run didn't count).
    """
    existing = load_json_report(report_dir, source_path)
    if existing is None:
        return False
    return existing.get("overall_status") != "TOOL_FAILURE"
