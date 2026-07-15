"""CSV summary — one row per file per run.

Extends smpl_qc_v210.py's working to_csv_row()/CSV_COLUMNS pattern with
`mode` and `matched_patterns` columns, plus mode-specific extensions
(vendor-qc adds `profile`; donor-triage omits it).
"""

from __future__ import annotations

import csv
from pathlib import Path

from sqc.report.schema import FileReport

BASE_CSV_COLUMNS = [
    "filename", "mode", "overall_status", "file_size_bytes",
    "video_codec", "width", "height", "fps_rational",
    "audio_codec", "audio_sample_rate",
    "frame_analysis_done", "anomalous_frame_count", "anomalous_frame_type",
    "trim_duration_s", "matched_patterns", "error",
]

VENDOR_QC_CSV_COLUMNS = BASE_CSV_COLUMNS[:2] + ["profile"] + BASE_CSV_COLUMNS[2:]
DONOR_TRIAGE_CSV_COLUMNS = BASE_CSV_COLUMNS


def _probe_video_stream(probe_data: dict) -> dict:
    for s in probe_data.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return {}


def _probe_audio_stream(probe_data: dict) -> dict:
    for s in probe_data.get("streams", []):
        if s.get("codec_type") == "audio":
            return s
    return {}


def to_csv_row(report: FileReport) -> dict:
    vs = _probe_video_stream(report.probe_data)
    as1 = _probe_audio_stream(report.probe_data)
    fs = report.frame_stats

    row = {
        "filename": report.path.name,
        "mode": report.mode,
        "overall_status": report.overall_status,
        "file_size_bytes": report.file_size,
        "video_codec": vs.get("codec_name", ""),
        "width": vs.get("width", ""),
        "height": vs.get("height", ""),
        "fps_rational": vs.get("r_frame_rate", ""),
        "audio_codec": as1.get("codec_name", ""),
        "audio_sample_rate": as1.get("sample_rate", ""),
        "frame_analysis_done": "yes" if fs else "no",
        "anomalous_frame_count": fs.anomalous_count if fs else "",
        "anomalous_frame_type": fs.classification if fs else "",
        "trim_duration_s": f"{fs.trim_duration_s:.6f}" if (fs and fs.trim_duration_s is not None) else "",
        "matched_patterns": ";".join(report.matched_patterns),
        "error": report.error or "",
    }
    if report.mode == "vendor_qc":
        row["profile"] = report.profile_name or ""
    return row


def write_csv(reports: list[FileReport], csv_path: Path, mode: str) -> None:
    columns = VENDOR_QC_CSV_COLUMNS if mode == "vendor_qc" else DONOR_TRIAGE_CSV_COLUMNS
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in reports:
            writer.writerow(to_csv_row(r))
