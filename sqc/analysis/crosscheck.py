"""Shared, mode-agnostic cross-tool comparison and container/essence integrity checks.

Runs identically for vendor-qc and donor-triage — "never trust the file
extension," disagreements between MediaInfo/ffprobe/MediaTrace are more
diagnostic than any single tool's output, and known-benign tool warnings
(e.g. the AJA metadata-track "unsupported codec id 0" notice) are demoted to
INFO so they don't mask real problems. Adapted from smpl_qc_v210.py's
check_integrity()/check_container()/check_timecode_track(), generalized to
not assume a specific codec/resolution/fps policy (that's vendor-qc's job,
via policy.py + tools/mediaconch.py) or a tmcd timecode track's presence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqc.report.schema import CheckResult
from sqc.util import parse_rational, to_float, to_int

BENIGN_STDERR_PATTERNS = [
    "unsupported codec with id 0",  # AJA/QuickTime proprietary metadata track
    "deprecated pixel format",
    "invalid dropping",             # minor edit-list rounding
]

MOOV_REQUIRED_FORMATS = ("mov", "mp4", "m4a", "3gp", "3g2", "mj2")


def check_probe_integrity(probe_stderr: str) -> list[CheckResult]:
    """Surface any structural errors/warnings ffprobe emitted, suppressing
    known-benign patterns to INFO so they don't mask real problems."""
    if not probe_stderr:
        return [CheckResult("probe_integrity", "PASS", "ffprobe reported no errors or warnings")]

    lines = [ln for ln in probe_stderr.splitlines() if ln.strip()]
    benign_lines, problem_lines = [], []
    for ln in lines:
        ln_lower = ln.lower()
        if any(pat in ln_lower for pat in BENIGN_STDERR_PATTERNS):
            benign_lines.append(ln)
        else:
            problem_lines.append(ln)

    results = []
    if benign_lines:
        results.append(CheckResult(
            "probe_integrity_notice", "INFO",
            f"{len(benign_lines)} known-benign ffprobe notice(s) — example: {benign_lines[0][:120]}",
        ))

    if not problem_lines:
        suffix = f" ({len(benign_lines)} benign notice(s) suppressed)" if benign_lines else ""
        results.append(CheckResult("probe_integrity", "PASS", f"No structural errors or unexpected warnings{suffix}"))
    else:
        first = problem_lines[0].lower()
        if "moov atom not found" in first:
            results.append(CheckResult(
                "probe_integrity", "FAIL",
                f"ffprobe: {problem_lines[0][:200]}", pattern_id="MISSING_MOOV_ATOM",
            ))
        else:
            # check_probe_integrity is only ever called with stderr from a probe
            # that already succeeded (probe_file() raises on nonzero exit, caught
            # upstream as its own FAIL/TOOL_FAILURE) — so anything reaching here
            # is decoder-level chatter ffprobe judged warning-severity via
            # `-v warning`, not a structural failure. Default to WARN rather than
            # text-sniffing for "warning"/"deprecated" substrings, which misses
            # plenty of genuinely benign codec-specific notices (e.g. HEVC's
            # "Unexpected extra rep formats") and would otherwise false-positive
            # FAIL on donor-triage's heterogeneous file population.
            results.append(CheckResult(
                "probe_integrity", "WARN",
                f"ffprobe emitted {len(problem_lines)} unclassified warning-level line(s) — "
                f"first: {problem_lines[0][:200]}",
            ))
    return results


def check_moov_atom(mediatrace_data: dict, format_name: str) -> list[CheckResult]:
    """Cross-check moov-atom presence against MediaTrace's binary anatomy for
    QuickTime/MP4-family containers (no-op for other formats)."""
    if not any(fmt in (format_name or "").lower() for fmt in MOOV_REQUIRED_FORMATS):
        return [CheckResult("moov_atom", "SKIP", f"Not a QuickTime/MP4-family container ({format_name!r})")]

    if not mediatrace_data:
        return [CheckResult("moov_atom", "SKIP", "MediaTrace data unavailable")]

    if _tree_contains_value(mediatrace_data, "moov"):
        return [CheckResult("moov_atom", "PASS", "moov atom present")]
    return [CheckResult(
        "moov_atom", "FAIL", "No moov atom found in MediaTrace binary anatomy",
        pattern_id="MISSING_MOOV_ATOM",
    )]


def _tree_contains_value(node, target: str) -> bool:
    if isinstance(node, dict):
        return any(_tree_contains_value(v, target) for v in node.values())
    if isinstance(node, list):
        return any(_tree_contains_value(v, target) for v in node)
    return node == target


def check_extension_format_match(path: Path, format_name: str) -> list[CheckResult]:
    """Extension is never trusted as the actual format — this check only
    flags a WARN when they disagree, it never gates format routing."""
    ext = path.suffix.lower().lstrip(".")
    if not ext or not format_name:
        return [CheckResult("extension_format_match", "SKIP", "Extension or format_name unavailable")]

    fmt_tokens = [t.strip().lower() for t in format_name.replace(",", " ").split()]
    if ext in fmt_tokens or any(ext in t for t in fmt_tokens):
        return [CheckResult("extension_format_match", "PASS", f".{ext} matches detected format {format_name!r}")]
    return [CheckResult(
        "extension_format_match", "WARN",
        f".{ext} does not match detected format {format_name!r}",
        pattern_id="EXTENSION_FORMAT_MISMATCH",
    )]


def check_container_codec_validity(probe: dict) -> list[CheckResult]:
    """Flag a video stream whose codec_tag_string (the raw fourcc found in
    the container) didn't resolve to any codec_name ffprobe recognizes —
    a reasonable proxy for a "Frankenstein" file (codec not valid for its
    declared container) without needing per-container-format codec tables.
    A stream ffprobe fully understands always has a non-empty codec_name;
    an unresolved but present tag is the mismatch signal."""
    video_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    results = []
    for s in video_streams:
        codec_name = (s.get("codec_name") or "").lower()
        tag = (s.get("codec_tag_string") or "").strip().strip("[]0")
        if codec_name in ("", "none", "unknown") and tag:
            results.append(CheckResult(
                "container_codec_validity", "FAIL",
                f"Video stream has codec tag {s.get('codec_tag_string')!r} that ffprobe could not "
                f"resolve to a known codec — possible container/codec mismatch",
                pattern_id="CONTAINER_CODEC_MISMATCH",
            ))
    if not results:
        results.append(CheckResult("container_codec_validity", "PASS", "All streams have recognized codecs"))
    return results


def check_stream_inventory(probe: dict) -> list[CheckResult]:
    streams = probe.get("streams", [])
    video_count = sum(1 for s in streams if s.get("codec_type") == "video")
    audio_count = sum(1 for s in streams if s.get("codec_type") == "audio")

    results = []
    if video_count == 1:
        results.append(CheckResult("stream_video_count", "PASS", "1 video stream"))
    elif video_count == 0:
        results.append(CheckResult("stream_video_count", "FAIL", "No video stream found"))
    else:
        results.append(CheckResult(
            "stream_video_count", "WARN", f"{video_count} video streams (expected 1)",
            pattern_id="MULTI_VIDEO_STREAM",
        ))

    if audio_count >= 1:
        results.append(CheckResult("stream_audio_count", "PASS", f"{audio_count} audio stream(s)"))
    else:
        results.append(CheckResult("stream_audio_count", "WARN", "No audio stream found"))

    return results


def check_av_duration_sync(probe: dict, threshold_s: float = 1.0) -> list[CheckResult]:
    streams = probe.get("streams", [])
    video_s = [s for s in streams if s.get("codec_type") == "video"]
    audio_s = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_s or not audio_s:
        return [CheckResult("av_duration_sync", "SKIP", "Need at least one video and one audio stream")]

    v_dur, a_dur = to_float(video_s[0].get("duration")), to_float(audio_s[0].get("duration"))
    if v_dur is None or a_dur is None:
        return [CheckResult("av_duration_sync", "SKIP", "Duration not available for one or both streams")]

    delta = abs(v_dur - a_dur)
    if delta <= threshold_s:
        return [CheckResult("av_duration_sync", "PASS", f"{delta:.4f}s (threshold {threshold_s}s)")]
    return [CheckResult(
        "av_duration_sync", "WARN",
        f"{delta:.4f}s — audio and video durations differ by more than {threshold_s}s",
        pattern_id="STREAM_DURATION_MISMATCH",
    )]


def check_frame_count_vs_duration(probe: dict) -> list[CheckResult]:
    """Generic version of smpl_qc_v210.py's check_timecode_track(), without
    requiring a tmcd track: compares the video stream's own nb_frames against
    round(duration x fps). A non-zero delta doesn't assert a verdict on its
    own — it's WARN regardless of magnitude; analysis/frame_timing.py's
    classification is what determines whether it's a benign SPIN_DOWN/
    TIMEBASE_ROUNDING artifact or genuine DROPPED_FRAMES (see modes/*.py's
    reconciliation step)."""
    video_s = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if not video_s:
        return [CheckResult("frame_count_vs_duration", "SKIP", "No video stream")]

    vs = video_s[0]
    v_actual = to_int(vs.get("nb_frames"))
    v_duration = to_float(vs.get("duration"))
    v_fps = parse_rational(vs.get("r_frame_rate", ""))

    if v_actual is None:
        return [CheckResult("frame_count_vs_duration", "SKIP", "nb_frames not available")]
    if v_duration is None or not v_fps or v_fps[0] <= 0:
        return [CheckResult("frame_count_vs_duration", "SKIP", f"Could not derive expected frame count (duration={v_duration}, fps={v_fps})")]

    v_expected = round(v_duration * v_fps[0] / v_fps[1])
    delta = v_actual - v_expected
    if delta == 0:
        return [CheckResult("frame_count_vs_duration", "PASS", f"Frame count matches duration-derived expected: {v_actual}")]

    note = "consistent with small tail artifact" if abs(delta) <= 5 else (
        "large delta — see frame_timing classification for determination"
    )
    return [CheckResult(
        "frame_count_vs_duration", "WARN",
        f"Discrepancy: actual={v_actual}, expected={v_expected}, delta={delta:+d} — {note}",
    )]


def check_cross_tool_duration(probe: dict, mediainfo_data: dict, threshold_s: float = 1.0) -> list[CheckResult]:
    """Compare MediaInfo's reported duration against ffprobe's — the
    "reported vs actual" cross-check Doc A calls out as a truncation signal:
    if MediaInfo reports N minutes but ffprobe's container index only
    accounts for M < N minutes, the file may be truncated."""
    ffprobe_dur = to_float(probe.get("format", {}).get("duration"))
    if ffprobe_dur is None:
        return [CheckResult("cross_tool_duration", "SKIP", "ffprobe duration unavailable")]

    mi_dur = _extract_mediainfo_duration_s(mediainfo_data)
    if mi_dur is None:
        return [CheckResult("cross_tool_duration", "SKIP", "MediaInfo duration unavailable")]

    delta = abs(mi_dur - ffprobe_dur)
    if delta <= threshold_s:
        return [CheckResult("cross_tool_duration", "PASS", f"MediaInfo/ffprobe duration agree within {threshold_s}s ({delta:.3f}s delta)")]
    return [CheckResult(
        "cross_tool_duration", "WARN",
        f"MediaInfo reports {mi_dur:.3f}s, ffprobe reports {ffprobe_dur:.3f}s "
        f"(delta {delta:.3f}s) — possible truncation or partial write",
    )]


def _extract_mediainfo_duration_s(mediainfo_data: dict) -> Optional[float]:
    """MediaInfo's JSON General track reports Duration in seconds as a
    decimal string (e.g. "17.000"), confirmed against a real local .mov file."""
    tracks = (mediainfo_data or {}).get("media", {}).get("track", [])
    for t in tracks:
        if t.get("@type") == "General":
            return to_float(t.get("Duration"))
    return None


def run_crosscheck(
    path: Path,
    probe: dict,
    probe_stderr: str,
    mediainfo_data: dict,
    mediatrace_data: dict,
    av_duration_threshold_s: float = 1.0,
) -> list[CheckResult]:
    """Run the full shared crosscheck layer. Returns a flat list of CheckResult."""
    fmt = probe.get("format", {})
    format_name = fmt.get("format_name", "")

    results: list[CheckResult] = []
    results += check_probe_integrity(probe_stderr)
    results += check_extension_format_match(path, format_name)
    results += check_container_codec_validity(probe)
    results += check_stream_inventory(probe)
    results += check_av_duration_sync(probe, av_duration_threshold_s)
    results += check_frame_count_vs_duration(probe)
    results += check_moov_atom(mediatrace_data, format_name)
    results += check_cross_tool_duration(probe, mediainfo_data, av_duration_threshold_s)
    return results
