"""donor-triage mode: well-formedness only, no spec.

Covers donor collections and institutional-partner collection addenda
(including raw camera cards) alike — per user decision, the distinction
between "donor" and "partner addendum" was judged too subtle to warrant a
separate third mode. Orchestrates the shared crosscheck layer, frame-timing
detection (interpreted with reduced/generic severity — never asserts
spin-down-vs-drops the way vendor-qc does), and the ffmpeg null-pass essence
check, which defaults on here since it's this mode's main defense against
essence-level corruption in unknown-provenance files with no policy to check
metadata against.
"""

from __future__ import annotations

from pathlib import Path

from sqc.analysis.crosscheck import run_crosscheck
from sqc.analysis.frame_timing import classify_frame_timing
from sqc.analysis.patterns import get_pattern
from sqc.config import DonorTriageConfig
from sqc.report.schema import CheckResult, FileReport
from sqc.tools import exiftool, ffmpeg_null, ffprobe, mediainfo, mediatrace


def _interpret_frame_stats(stats) -> list[CheckResult]:
    if stats is None:
        return [CheckResult("frame_timing", "SKIP", "No video packet durations returned")]

    if stats.classification == "NONE":
        return [CheckResult("frame_timing", "PASS", f"All {stats.total_frames} frames have nominal duration")]

    if stats.classification == "TIMEBASE_ROUNDING":
        pattern = get_pattern("VFR_TIMEBASE_ROUNDING")
        return [CheckResult(
            "frame_timing", pattern.severity_for_mode("donor_triage"),
            "Timebase rounding artifact (alternating tick durations, no large anomalies) — benign",
            pattern_id=pattern.pattern_id,
        )]

    # SPIN_DOWN or DROPPED_FRAMES: donor-triage doesn't assume tape-capture
    # semantics for arbitrary donor material (raw camera cards, edited masters
    # may have legitimately intentional VFR) — surface as generic detail only.
    return [CheckResult(
        "frame_timing", "WARN",
        f"Variable frame rate detected: {stats.anomalous_count} anomalous frame duration(s) "
        f"out of {stats.total_frames} (see frame_stats.anomalous_positions for detail) — "
        f"informational; donor-triage does not assume tape-capture VFR causes for arbitrary material",
    )]


def process_file(path: Path, config: DonorTriageConfig) -> FileReport:
    report = FileReport(path=path, mode="donor_triage")
    report.file_size = path.stat().st_size

    try:
        probe, probe_stderr = ffprobe.probe_file(path)
    except Exception as e:
        report.error = str(e)
        report.add(CheckResult("ffprobe_probe", "FAIL", f"ffprobe failed: {e}"))
        return report
    report.probe_data = probe

    try:
        report.mediainfo_data = mediainfo.run_mediainfo(path)
    except Exception as e:
        report.add(CheckResult("mediainfo", "SKIP", f"mediainfo failed: {e}"))

    try:
        report.mediatrace_data = mediatrace.run_mediatrace(path)
    except Exception as e:
        report.add(CheckResult("mediatrace", "SKIP", f"mediatrace failed: {e}"))

    try:
        report.exiftool_data = exiftool.run_exiftool(path)
    except Exception as e:
        report.add(CheckResult("exiftool", "SKIP", f"exiftool failed: {e}"))

    report.add_all(run_crosscheck(
        path, report.probe_data, probe_stderr, report.mediainfo_data, report.mediatrace_data,
    ))

    if config.batch.full:
        try:
            durations = ffprobe.get_packet_durations(path)
            stats = classify_frame_timing(durations)
            report.frame_stats = stats
            report.add_all(_interpret_frame_stats(stats))
        except Exception as e:
            report.add(CheckResult("frame_timing", "SKIP", f"frame timing analysis failed: {e}"))

    if config.strict_decode_check:
        try:
            report.add_all(ffmpeg_null.run_essence_checks(path))
        except Exception as e:
            report.add(CheckResult("essence_null_pass", "SKIP", f"null-pass check failed: {e}"))

    return report
