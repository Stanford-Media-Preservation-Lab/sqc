"""Config dataclasses, built once from parsed argparse args and threaded
through instead of passing `args` around — matches srw.cli.Config."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_DONOR_TRIAGE_EXTENSIONS = [
    ".mov", ".mp4", ".mkv", ".mxf", ".avi", ".wav", ".dv", ".m4v",
]


@dataclass
class BatchConfig:
    """Fields shared by both modes."""
    input_path: Path
    extensions: list[str]
    report_dir: Path
    csv_path: Path
    log_file: Path
    workers: Optional[int] = None  # None -> len(files); never a hardcoded CPU-derived guess
    resume: bool = True
    full: bool = False  # frame-level packet timing analysis


@dataclass
class VendorQCConfig:
    batch: BatchConfig
    profile_name: str
    profiles_dir: Path
    mediaconch_dir: Path
    strict_decode_check: bool = False  # opt-in; MediaConch+crosscheck carry most of the weight
    # Ad-hoc override layered on top of the loaded profile, without editing the file.
    # VFR-taxonomy thresholds (spin_down_zone, frame_anomaly_*) are intentionally
    # profile-only, not CLI flags — that taxonomy's specific tuning knobs were
    # overpromoted for what turned out to be one vendor's isolated tape/signal-chain
    # issue; see CLAUDE.md's "VFR taxonomy de-emphasis" entry.
    av_duration_threshold_s: Optional[float] = None


@dataclass
class DonorTriageConfig:
    batch: BatchConfig
    strict_decode_check: bool = True  # default on — this mode's whole point is "tell me if it's broken"
