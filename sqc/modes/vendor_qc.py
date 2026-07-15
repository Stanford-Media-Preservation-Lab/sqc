"""vendor-qc mode: spec conformance against a pluggable policy profile.

Orchestrates the shared crosscheck layer plus vendor-qc-only layers: direct
ffprobe-based technical-attribute checks against the profile's [video]/[audio]
sections (generalized from smpl_qc_v210.py's check_video_stream()/
check_audio_streams(), parametrized by the loaded profile instead of a
hardcoded POLICY_DEFAULTS dict), the MediaConch policy XML check, and the
full VFR taxonomy with full severity mapping (SPIN_DOWN/TIMEBASE_ROUNDING are
WARN, DROPPED_FRAMES is FAIL) — vendor-qc, unlike donor-triage, treats this
classification as an actionable verdict because it's checking against a
written vendor spec for known tape-digitization equipment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqc.analysis.crosscheck import run_crosscheck
from sqc.analysis.frame_timing import classify_frame_timing
from sqc.analysis.patterns import get_pattern
from sqc.config import VendorQCConfig
from sqc.policy import PolicyProfile, load_profile
from sqc.report.schema import CheckResult, FileReport
from sqc.tools import exiftool, ffmpeg_null, ffprobe, mediaconch, mediainfo, mediatrace
from sqc.util import parse_rational, to_int


def _capture_quirk_input_args(profile: PolicyProfile) -> Optional[list[str]]:
    if profile.capture_quirks.get("apply_cropping_zero"):
        return ["-apply_cropping", "0"]
    return None


def check_video_policy(probe: dict, video_policy: dict) -> list[CheckResult]:
    streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if not streams:
        return [CheckResult("video_policy", "SKIP", "No video stream")]
    vs = streams[0]
    results = []

    codec = vs.get("codec_name", "")
    exp_codec = video_policy.get("codec")
    if exp_codec:
        results.append(CheckResult(
            "video_codec", "PASS" if codec == exp_codec else "FAIL",
            f"{codec}" + (f" (expected {exp_codec})" if codec != exp_codec else ""),
        ))

    w, h = vs.get("width"), vs.get("height")
    exp_w, exp_h = video_policy.get("width"), video_policy.get("height")
    if exp_w and exp_h:
        results.append(CheckResult(
            "video_resolution", "PASS" if (w == exp_w and h == exp_h) else "WARN",
            f"{w}x{h}" + (f" (policy: {exp_w}x{exp_h})" if (w, h) != (exp_w, exp_h) else ""),
        ))

    fps_str = vs.get("r_frame_rate", "")
    fps = parse_rational(fps_str)
    exp_num, exp_den = video_policy.get("fps_num"), video_policy.get("fps_den")
    if exp_num and exp_den:
        matches = fps and fps[0] == exp_num and fps[1] == exp_den
        results.append(CheckResult(
            "video_fps", "PASS" if matches else "WARN",
            fps_str + (f" (policy: {exp_num}/{exp_den})" if not matches else ""),
        ))

    tb = vs.get("time_base", "")
    mul = video_policy.get("timescale_multiple")
    if mul:
        timescale = None
        if "/" in tb:
            try:
                timescale = int(tb.split("/")[1])
            except (ValueError, IndexError):
                pass
        if timescale is None:
            results.append(CheckResult("video_timescale", "WARN", f"Cannot parse time_base: {tb!r}"))
        elif timescale % mul == 0:
            results.append(CheckResult("video_timescale", "PASS", f"{timescale} is a multiple of {mul}"))
        else:
            results.append(CheckResult(
                "video_timescale", "WARN",
                f"{timescale} is not a multiple of {mul} — will cause MediaInfo VFR flag",
                pattern_id="VFR_TIMEBASE_ROUNDING",
            ))

    bps = to_int(vs.get("bits_per_raw_sample")) or to_int(vs.get("bits_per_coded_sample"))
    exp_bps = video_policy.get("bit_depth")
    if exp_bps:
        if bps is None:
            results.append(CheckResult("video_bit_depth", "WARN", "Bit depth not declared in stream metadata"))
        else:
            results.append(CheckResult(
                "video_bit_depth", "PASS" if bps == exp_bps else "FAIL",
                f"{bps} bits" + (f" (expected {exp_bps})" if bps != exp_bps else ""),
            ))

    fo = vs.get("field_order", "")
    exp_fos = video_policy.get("field_order")
    if exp_fos:
        results.append(CheckResult(
            "video_field_order", "PASS" if fo in exp_fos else "WARN",
            f"field_order={fo!r}" + (f" (policy accepts {exp_fos!r})" if fo not in exp_fos else ""),
        ))

    return results


def check_audio_policy(probe: dict, audio_policy: dict) -> list[CheckResult]:
    audio_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    min_streams = audio_policy.get("min_streams", 1)
    if len(audio_streams) < min_streams:
        return [CheckResult("audio_policy", "WARN", f"{len(audio_streams)} audio stream(s) (expected >= {min_streams})")]

    results = []
    exp_prefix = audio_policy.get("codec_prefix")
    exp_depth = audio_policy.get("bit_depth")
    exp_rate = audio_policy.get("sample_rate")

    for i, s in enumerate(audio_streams):
        label = f"audio[{i}]"
        codec = s.get("codec_name", "")
        depth = to_int(s.get("bits_per_raw_sample")) or to_int(s.get("bits_per_coded_sample"))
        rate = to_int(s.get("sample_rate"))

        if exp_prefix:
            results.append(CheckResult(
                f"{label}_codec", "PASS" if codec.startswith(exp_prefix) else "WARN",
                f"{codec!r}" + (f" (expected {exp_prefix}*)" if not codec.startswith(exp_prefix) else ""),
            ))
        if exp_depth:
            results.append(CheckResult(
                f"{label}_bit_depth", "PASS" if depth == exp_depth else "FAIL",
                f"{depth}-bit" + (f" (expected {exp_depth}-bit)" if depth != exp_depth else ""),
            ))
        if exp_rate:
            results.append(CheckResult(
                f"{label}_sample_rate", "PASS" if rate == exp_rate else "WARN",
                f"{rate} Hz" + (f" (expected {exp_rate} Hz)" if rate != exp_rate else ""),
            ))

    return results


def check_mediaconch_policy(path: Path, profile: PolicyProfile) -> list[CheckResult]:
    if not profile.mediaconch_policy.is_file():
        return [CheckResult(
            "mediaconch_policy", "SKIP",
            f"Policy file not found: {profile.mediaconch_policy}",
        )]
    _, is_valid = next(mediaconch.validate_files_against_policy([path], profile.mediaconch_policy, batch_size=1))
    if is_valid:
        return [CheckResult("mediaconch_policy", "PASS", f"Conforms to MediaConch policy {profile.name!r}")]
    detail = mediaconch.get_policy_detail(profile.mediaconch_policy, path)
    return [CheckResult(
        "mediaconch_policy", "FAIL",
        f"Does not conform to MediaConch policy {profile.name!r}: {detail[:400]}",
    )]


def _interpret_frame_stats(stats, thresholds: dict) -> list[CheckResult]:
    if stats is None:
        return [CheckResult("frame_timing", "SKIP", "No video packet durations returned")]

    if stats.classification == "NONE":
        return [CheckResult("frame_timing", "PASS", f"All {stats.total_frames} frames have nominal duration")]

    if stats.classification == "TIMEBASE_ROUNDING":
        pattern = get_pattern("VFR_TIMEBASE_ROUNDING")
        return [CheckResult(
            "frame_timing", pattern.severity_for_mode("vendor_qc"),
            "Timebase rounding artifact (alternating tick durations) — cosmetic, "
            "lossless remux with -video_track_timescale fixes it if a clean CFR file is needed",
            pattern_id=pattern.pattern_id,
        )]

    if stats.classification == "SPIN_DOWN":
        pattern = get_pattern("VFR_TAIL_ARTIFACT")
        spin_zone = thresholds.get("spin_down_zone", 0.97)
        detail = (
            f"{stats.anomalous_count} double-duration frame(s) at end of file "
            f"(>= {spin_zone * 100:.0f}% through) — consistent with VTR head spin-down"
        )
        if stats.trim_duration_s is not None:
            detail += f"; trim_duration_s={stats.trim_duration_s:.6f}"
        return [CheckResult(
            "frame_timing", pattern.severity_for_mode("vendor_qc"), detail,
            value=stats.trim_duration_s,
            pattern_id=pattern.pattern_id,
        )]

    # DROPPED_FRAMES
    pattern = get_pattern("VFR_GENUINE_DROPS")
    return [CheckResult(
        "frame_timing", pattern.severity_for_mode("vendor_qc"),
        f"{stats.anomalous_count} anomalous frame duration(s) distributed across the file "
        f"— probable dropped frames during capture; return to vendor / re-digitize",
        pattern_id=pattern.pattern_id,
    )]


def process_file(path: Path, config: VendorQCConfig) -> FileReport:
    profile = load_profile(config.profile_name, config.profiles_dir, config.mediaconch_dir)

    # Ad-hoc CLI overrides layered on top of the loaded profile.
    thresholds = dict(profile.thresholds)
    for key, override in (
        ("spin_down_zone", config.spin_down_zone),
        ("frame_anomaly_low_ratio", config.frame_anomaly_low_ratio),
        ("frame_anomaly_high_ratio", config.frame_anomaly_high_ratio),
        ("av_duration_threshold_s", config.av_duration_threshold_s),
    ):
        if override is not None:
            thresholds[key] = override

    report = FileReport(path=path, mode="vendor_qc", profile_name=profile.name)
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
        av_duration_threshold_s=thresholds.get("av_duration_threshold_s", 1.0),
    ))

    report.add_all(check_video_policy(probe, profile.video))
    report.add_all(check_audio_policy(probe, profile.audio))

    try:
        report.add_all(check_mediaconch_policy(path, profile))
    except Exception as e:
        report.add(CheckResult("mediaconch_policy", "SKIP", f"mediaconch check failed: {e}"))

    if config.batch.full:
        try:
            durations = ffprobe.get_packet_durations(path)
            stats = classify_frame_timing(durations, {
                "spin_down_zone": thresholds.get("spin_down_zone", 0.97),
                "frame_anomaly_low_ratio": thresholds.get("frame_anomaly_low_ratio", 0.5),
                "frame_anomaly_high_ratio": thresholds.get("frame_anomaly_high_ratio", 1.5),
            })
            report.frame_stats = stats
            report.add_all(_interpret_frame_stats(stats, thresholds))
        except Exception as e:
            report.add(CheckResult("frame_timing", "SKIP", f"frame timing analysis failed: {e}"))

    if config.strict_decode_check:
        try:
            report.add_all(ffmpeg_null.run_essence_checks(path, extra_input_args=_capture_quirk_input_args(profile)))
        except Exception as e:
            report.add(CheckResult("essence_null_pass", "SKIP", f"null-pass check failed: {e}"))

    return report
