"""Unit tests for analysis/crosscheck.py.

All functions here are pure — they operate on already-obtained probe/
mediainfo/mediatrace dicts, no subprocess calls — so no mocking is needed.
Real tool integration (tools/*.py) is validated manually.
"""

from pathlib import Path

from sqc.analysis.crosscheck import (
    check_av_duration_sync,
    check_container_codec_validity,
    check_cross_tool_duration,
    check_extension_format_match,
    check_frame_count_vs_duration,
    check_moov_atom,
    check_probe_integrity,
    check_stream_inventory,
    run_crosscheck,
)


class TestCheckProbeIntegrity:
    def test_empty_stderr_passes(self):
        results = check_probe_integrity("")
        assert results[0].status == "PASS"

    def test_benign_pattern_demoted_to_info(self):
        results = check_probe_integrity("Unsupported codec with id 0 for input stream 1")
        statuses = {r.name: r.status for r in results}
        assert statuses["probe_integrity_notice"] == "INFO"
        assert statuses["probe_integrity"] == "PASS"

    def test_moov_atom_missing_message_is_fail_with_pattern(self):
        results = check_probe_integrity("moov atom not found")
        assert results[-1].status == "FAIL"
        assert results[-1].pattern_id == "MISSING_MOOV_ATOM"

    def test_unclassified_warning_defaults_to_warn_not_fail(self):
        # A successful probe (returncode 0) that still emitted warning-level
        # stderr should never escalate to FAIL just because the text doesn't
        # literally contain "warning"/"deprecated" — see crosscheck.py's
        # docstring for why (this was a real false-positive found during
        # development against an HEVC .mov with decoder-specific chatter).
        results = check_probe_integrity("[hevc @ 0x0] Unexpected extra rep formats")
        assert results[-1].status == "WARN"


class TestCheckExtensionFormatMatch:
    def test_matching_extension_passes(self):
        result = check_extension_format_match(Path("file.mov"), "mov,mp4,m4a,3gp,3g2,mj2")
        assert result[0].status == "PASS"

    def test_mismatched_extension_warns_with_pattern(self):
        result = check_extension_format_match(Path("file.mp4"), "matroska,webm")
        assert result[0].status == "WARN"
        assert result[0].pattern_id == "EXTENSION_FORMAT_MISMATCH"

    def test_missing_extension_warns_with_pattern(self):
        result = check_extension_format_match(Path("file_no_ext"), "mov,mp4,m4a,3gp,3g2,mj2")
        assert result[0].status == "WARN"
        assert result[0].pattern_id == "EXTENSION_FORMAT_MISMATCH"
        assert "no extension" in result[0].detail.lower()

    def test_missing_format_name_is_skip_not_warn(self):
        result = check_extension_format_match(Path("file.mov"), "")
        assert result[0].status == "SKIP"


class TestCheckContainerCodecValidity:
    def test_recognized_codec_passes(self):
        probe = {"streams": [{"codec_type": "video", "codec_name": "v210", "codec_tag_string": "v210"}]}
        results = check_container_codec_validity(probe)
        assert results[0].status == "PASS"

    def test_unresolved_tag_fails_with_pattern(self):
        probe = {"streams": [{"codec_type": "video", "codec_name": "", "codec_tag_string": "xyz1"}]}
        results = check_container_codec_validity(probe)
        assert results[0].status == "FAIL"
        assert results[0].pattern_id == "CONTAINER_CODEC_MISMATCH"


class TestCheckStreamInventory:
    def test_single_video_single_audio(self):
        probe = {"streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}
        results = check_stream_inventory(probe)
        statuses = {r.name: r.status for r in results}
        assert statuses["stream_video_count"] == "PASS"
        assert statuses["stream_audio_count"] == "PASS"

    def test_no_video_stream_fails(self):
        probe = {"streams": [{"codec_type": "audio"}]}
        results = check_stream_inventory(probe)
        assert [r for r in results if r.name == "stream_video_count"][0].status == "FAIL"

    def test_multiple_video_streams_warns_with_pattern(self):
        probe = {"streams": [{"codec_type": "video"}, {"codec_type": "video"}]}
        results = check_stream_inventory(probe)
        video_result = [r for r in results if r.name == "stream_video_count"][0]
        assert video_result.status == "WARN"
        assert video_result.pattern_id == "MULTI_VIDEO_STREAM"

    def test_no_audio_warns_without_failing(self):
        probe = {"streams": [{"codec_type": "video"}]}
        results = check_stream_inventory(probe)
        assert [r for r in results if r.name == "stream_audio_count"][0].status == "WARN"


class TestCheckAvDurationSync:
    def test_within_threshold_passes(self):
        probe = {"streams": [
            {"codec_type": "video", "duration": "10.0"},
            {"codec_type": "audio", "duration": "10.2"},
        ]}
        results = check_av_duration_sync(probe, threshold_s=1.0)
        assert results[0].status == "PASS"

    def test_beyond_threshold_warns_with_pattern(self):
        probe = {"streams": [
            {"codec_type": "video", "duration": "10.0"},
            {"codec_type": "audio", "duration": "5.0"},
        ]}
        results = check_av_duration_sync(probe, threshold_s=1.0)
        assert results[0].status == "WARN"
        assert results[0].pattern_id == "STREAM_DURATION_MISMATCH"


class TestCheckFrameCountVsDuration:
    def test_matching_count_passes(self):
        probe = {"streams": [{
            "codec_type": "video", "nb_frames": "300",
            "duration": "10.0", "r_frame_rate": "30/1",
        }]}
        results = check_frame_count_vs_duration(probe)
        assert results[0].status == "PASS"

    def test_mismatched_count_warns(self):
        probe = {"streams": [{
            "codec_type": "video", "nb_frames": "298",
            "duration": "10.0", "r_frame_rate": "30/1",
        }]}
        results = check_frame_count_vs_duration(probe)
        assert results[0].status == "WARN"


class TestCheckMoovAtom:
    def test_non_quicktime_format_is_skip(self):
        results = check_moov_atom({}, "matroska,webm")
        assert results[0].status == "SKIP"

    def test_present_moov_passes(self):
        trace = {"MediaTrace": {"media": {"block": [{"data": ["8", "moov"]}]}}}
        results = check_moov_atom(trace, "mov,mp4")
        assert results[0].status == "PASS"

    def test_missing_moov_fails_with_pattern(self):
        trace = {"MediaTrace": {"media": {"block": [{"data": ["8", "ftyp"]}]}}}
        results = check_moov_atom(trace, "mov,mp4")
        assert results[0].status == "FAIL"
        assert results[0].pattern_id == "MISSING_MOOV_ATOM"


class TestCheckCrossToolDuration:
    def test_agreeing_durations_pass(self):
        probe = {"format": {"duration": "17.000"}}
        mediainfo = {"media": {"track": [{"@type": "General", "Duration": "17.000"}]}}
        results = check_cross_tool_duration(probe, mediainfo)
        assert results[0].status == "PASS"

    def test_disagreeing_durations_warn(self):
        probe = {"format": {"duration": "17.000"}}
        mediainfo = {"media": {"track": [{"@type": "General", "Duration": "8.000"}]}}
        results = check_cross_tool_duration(probe, mediainfo)
        assert results[0].status == "WARN"


class TestRunCrosscheck:
    def test_runs_all_sub_checks_without_error(self):
        probe = {
            "format": {"duration": "10.0", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {"codec_type": "video", "codec_name": "v210", "duration": "10.0",
                 "nb_frames": "300", "r_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "pcm_s24le", "duration": "10.0"},
            ],
        }
        mediainfo = {"media": {"track": [{"@type": "General", "Duration": "10.0"}]}}
        mediatrace = {"MediaTrace": {"media": {"block": [{"data": ["8", "moov"]}]}}}
        results = run_crosscheck(Path("file.mov"), probe, "", mediainfo, mediatrace)
        assert len(results) > 0
        assert all(r.status in ("PASS", "WARN", "FAIL", "SKIP", "INFO") for r in results)
