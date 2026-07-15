from pathlib import Path

from sqc.report.csv_summary import to_csv_row, write_csv
from sqc.report.schema import CheckResult, FileReport, FrameStats, worst
from sqc.report.writer import (
    load_json_report,
    report_path_for,
    should_skip_for_resume,
    write_json_report,
)


class TestWorst:
    def test_fail_beats_warn(self):
        assert worst("PASS", "FAIL") == "FAIL"

    def test_tool_failure_beats_fail(self):
        assert worst("FAIL", "TOOL_FAILURE") == "TOOL_FAILURE"

    def test_pass_is_worse_than_skip_and_info_in_ranking_only(self):
        # PASS ranks "worse" than SKIP/INFO in STATUS_ORDER only in the sense
        # that a real check result should win over a non-committal one.
        assert worst("SKIP", "PASS") == "PASS"


class TestFileReportAdd:
    def test_add_updates_overall_status(self):
        report = FileReport(path=Path("f.mov"), mode="donor_triage")
        report.add(CheckResult("c1", "PASS", "ok"))
        assert report.overall_status == "PASS"
        report.add(CheckResult("c2", "FAIL", "bad"))
        assert report.overall_status == "FAIL"

    def test_add_tracks_matched_patterns(self):
        report = FileReport(path=Path("f.mov"), mode="donor_triage")
        report.add(CheckResult("c1", "WARN", "x", pattern_id="VFR_TAIL_ARTIFACT"))
        assert report.matched_patterns == ["VFR_TAIL_ARTIFACT"]
        report.add(CheckResult("c2", "WARN", "y", pattern_id="VFR_TAIL_ARTIFACT"))
        assert report.matched_patterns == ["VFR_TAIL_ARTIFACT"]  # no duplicates


class TestJsonRoundTrip:
    def test_to_json_dict_and_from_json_dict_round_trip(self, tmp_path):
        report = FileReport(path=Path("f.mov"), mode="vendor_qc", profile_name="v210_quad_ntsc")
        report.file_size = 12345
        report.add(CheckResult("check1", "WARN", "detail", pattern_id="VFR_TAIL_ARTIFACT"))
        report.frame_stats = FrameStats(
            total_frames=100, expected_duration=0.033, anomalous_count=1,
            anomalous_positions=[(99, 0.066)], min_duration=0.033, max_duration=0.066,
            duration_histogram={"0.033000s": 99}, classification="SPIN_DOWN", trim_duration_s=3.267,
        )

        written_path = write_json_report(report, tmp_path)
        assert written_path.exists()

        loaded = load_json_report(tmp_path, Path("f.mov"))
        reconstructed = FileReport.from_json_dict(loaded, Path("f.mov"))

        assert reconstructed.overall_status == "WARN"
        assert reconstructed.matched_patterns == ["VFR_TAIL_ARTIFACT"]
        assert reconstructed.frame_stats.classification == "SPIN_DOWN"
        assert reconstructed.frame_stats.trim_duration_s == 3.267

    def test_report_path_for_uses_stem(self, tmp_path):
        path = report_path_for(tmp_path, Path("/some/dir/example.mov"))
        assert path == tmp_path / "example_qc.json"


class TestShouldSkipForResume:
    def test_no_existing_report_means_do_not_skip(self, tmp_path):
        assert should_skip_for_resume(tmp_path, Path("missing.mov")) is False

    def test_completed_report_means_skip(self, tmp_path):
        report = FileReport(path=Path("done.mov"), mode="donor_triage")
        report.add(CheckResult("c", "PASS", "ok"))
        write_json_report(report, tmp_path)
        assert should_skip_for_resume(tmp_path, Path("done.mov")) is True

    def test_tool_failure_report_is_never_skipped(self, tmp_path):
        report = FileReport(path=Path("crashed.mov"), mode="donor_triage", overall_status="TOOL_FAILURE")
        write_json_report(report, tmp_path)
        assert should_skip_for_resume(tmp_path, Path("crashed.mov")) is False


class TestCsvSummary:
    def test_to_csv_row_includes_profile_for_vendor_qc(self):
        report = FileReport(path=Path("f.mov"), mode="vendor_qc", profile_name="v210_quad_ntsc")
        row = to_csv_row(report)
        assert row["profile"] == "v210_quad_ntsc"

    def test_to_csv_row_omits_profile_key_for_donor_triage(self):
        report = FileReport(path=Path("f.mov"), mode="donor_triage")
        row = to_csv_row(report)
        assert "profile" not in row

    def test_write_csv_produces_expected_header(self, tmp_path):
        report = FileReport(path=Path("f.mov"), mode="donor_triage")
        report.add(CheckResult("c", "PASS", "ok"))
        csv_path = tmp_path / "summary.csv"
        write_csv([report], csv_path, mode="donor_triage")
        content = csv_path.read_text()
        assert "filename" in content.splitlines()[0]
        assert "f.mov" in content
