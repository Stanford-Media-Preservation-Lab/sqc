"""VFR three-way taxonomy: timescale rounding / VTR spin-down / genuine drops.

This is a fresh, independent reimplementation of smpl_qc_v210.py's
analyze_frame_durations() (same algorithm, same thresholds), not an import of
that standalone script — see CLAUDE.md for why. classify_frame_timing() is a
pure function, used unchanged by both vendor-qc and donor-triage; each mode's
orchestrator (modes/vendor_qc.py, modes/donor_triage.py) maps the resulting
FrameStats.classification to severity differently — donor-triage never
asserts SPIN_DOWN-vs-DROPPED_FRAMES as an actionable verdict the way vendor-qc
does, since donor material may have legitimately intentional VFR that tape-
capture assumptions don't apply to.

Background on the three causes (all produce MediaInfo's "Minimum frame rate:
14.985 FPS" for 29.97fps content — that alone cannot distinguish them):
  - TIMEBASE_ROUNDING: video track timescale isn't a multiple of 30000, so the
    muxer alternates between two adjacent tick values at 29.97fps. Cosmetic;
    no frames are actually anomalous by duration ratio, this is a distinct
    smaller-magnitude signature (see _detect_timebase_rounding below).
  - SPIN_DOWN: one or more frames near the very end (>= spin_down_zone
    fraction through the file) have roughly double normal duration, from a
    VTR transport decelerating. Benign; trim at the first anomalous frame.
  - DROPPED_FRAMES: same double-duration signature but scattered throughout
    the file, not tail-only. Genuine capture failure; cannot be corrected.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from sqc.report.schema import FrameStats

DEFAULT_THRESHOLDS = {
    "spin_down_zone": 0.97,
    "frame_anomaly_low_ratio": 0.5,
    "frame_anomaly_high_ratio": 1.5,
}


def _detect_timebase_rounding(rounded: list[float], anomalous_count: int) -> bool:
    """Two distinct duration values, differing by a tiny amount, no large
    anomalies present — the alternating-tick rounding signature."""
    if anomalous_count != 0:
        return False
    unique_rounded = set(rounded)
    if len(unique_rounded) != 2:
        return False
    vals = sorted(unique_rounded)
    diff = vals[1] - vals[0]
    return diff < 0.001


def classify_frame_timing(durations: list[float], thresholds: Optional[dict] = None) -> Optional[FrameStats]:
    """Classify a list of per-frame packet durations (seconds) into the VFR taxonomy.

    Returns None if durations is empty (caller should treat that as its own
    SKIP/WARN condition — e.g. "no video packet durations returned").
    """
    if not durations:
        return None

    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    spin_zone = thresholds["spin_down_zone"]
    low_ratio = thresholds["frame_anomaly_low_ratio"]
    high_ratio = thresholds["frame_anomaly_high_ratio"]

    total = len(durations)
    rounded = [round(d, 6) for d in durations]
    counts = Counter(rounded)
    modal_dur = counts.most_common(1)[0][0]

    anomalous_positions = [
        (idx, d) for idx, d in enumerate(rounded)
        if d > modal_dur * high_ratio or d < modal_dur * low_ratio
    ]
    anomalous_count = len(anomalous_positions)
    min_dur = min(durations)
    max_dur = max(durations)
    hist = {f"{v:.6f}s": c for v, c in counts.most_common(10)}

    if anomalous_count == 0:
        classification = "TIMEBASE_ROUNDING" if _detect_timebase_rounding(rounded, anomalous_count) else "NONE"
    else:
        in_spin_zone = sum(1 for idx, _ in anomalous_positions if idx / total >= spin_zone)
        classification = "SPIN_DOWN" if in_spin_zone == anomalous_count else "DROPPED_FRAMES"

    trim_duration_s: Optional[float] = None
    if classification == "SPIN_DOWN" and anomalous_positions:
        first_bad_idx = anomalous_positions[0][0]
        trim_duration_s = sum(durations[:first_bad_idx])

    return FrameStats(
        total_frames=total,
        expected_duration=modal_dur,
        anomalous_count=anomalous_count,
        anomalous_positions=anomalous_positions[:50],  # cap for JSON size
        min_duration=min_dur,
        max_duration=max_dur,
        duration_histogram=hist,
        classification=classification,
        trim_duration_s=trim_duration_s,
    )
