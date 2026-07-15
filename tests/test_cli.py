"""Unit tests for cli.py's argparse wiring and defaults.

Only argument-parsing behavior is tested here — actual mode execution
(run_vendor_qc/run_donor_triage) shells out to real tools via batch.py and
is validated manually, matching srw/vdg's convention of not unit-testing
the subprocess-launching orchestration paths.
"""

from pathlib import Path

from sqc.cli import DONOR_TRIAGE_EPILOG, VENDOR_QC_EPILOG, build_arg_parser
from sqc.config import DEFAULT_DONOR_TRIAGE_EXTENSIONS


class TestTopLevelParser:
    def test_requires_a_subcommand(self, capsys):
        parser = build_arg_parser()
        try:
            parser.parse_args([])
            assert False, "should have exited"
        except SystemExit:
            pass

    def test_version_flag(self):
        parser = build_arg_parser()
        try:
            parser.parse_args(["--version"])
        except SystemExit as e:
            assert e.code == 0


class TestVendorQcArgParsing:
    def test_defaults(self):
        parser = build_arg_parser()
        args = parser.parse_args(["vendor-qc", "--profile", "v210_quad_ntsc", "input_dir"])
        assert args.command == "vendor-qc"
        assert args.profile == "v210_quad_ntsc"
        assert args.input == Path("input_dir")
        assert args.extensions is None  # resolved from profile at run time
        assert args.profiles_dir == Path("./profiles")
        assert args.mediaconch_dir == Path("./MediaConch")
        assert args.strict_decode_check is False
        assert args.resume is True
        assert args.full is False
        assert args.workers is None

    def test_profile_is_required(self):
        parser = build_arg_parser()
        try:
            parser.parse_args(["vendor-qc", "input_dir"])
            assert False, "should have exited (missing --profile)"
        except SystemExit:
            pass

    def test_no_resume_flag(self):
        parser = build_arg_parser()
        args = parser.parse_args(["vendor-qc", "--profile", "p", "--no-resume", "input_dir"])
        assert args.resume is False

    def test_av_duration_threshold_override(self):
        parser = build_arg_parser()
        args = parser.parse_args([
            "vendor-qc", "--profile", "p", "--av-duration-threshold", "2.5", "input_dir",
        ])
        assert args.av_duration_threshold_s == 2.5

    def test_no_spin_down_zone_flag_exists(self):
        # VFR-taxonomy thresholds are profile-only, not CLI-overridable — see
        # config.py's VendorQCConfig docstring and CLAUDE.md's "VFR taxonomy
        # de-emphasis" entry. This should fail to parse, not silently accept it.
        parser = build_arg_parser()
        try:
            parser.parse_args(["vendor-qc", "--profile", "p", "--spin-down-zone", "0.9", "input_dir"])
            assert False, "should have exited (--spin-down-zone is not a real flag)"
        except SystemExit:
            pass


class TestDonorTriageArgParsing:
    def test_defaults(self):
        parser = build_arg_parser()
        args = parser.parse_args(["donor-triage", "input_dir"])
        assert args.command == "donor-triage"
        assert args.extensions == list(DEFAULT_DONOR_TRIAGE_EXTENSIONS)
        assert args.strict_decode_check is True  # on by default, unlike vendor-qc
        assert args.resume is True
        assert args.full is False

    def test_no_strict_decode_check_flag(self):
        parser = build_arg_parser()
        args = parser.parse_args(["donor-triage", "--no-strict-decode-check", "input_dir"])
        assert args.strict_decode_check is False

    def test_custom_extensions(self):
        # The positional `input` must come before a `nargs="+"` option like
        # --extensions, or argparse greedily consumes it as an extra
        # extension value — see cli.py's module docstring / MANUAL.md.
        parser = build_arg_parser()
        args = parser.parse_args(["donor-triage", "input_dir", "--extensions", ".mov", ".mp4"])
        assert args.extensions == [".mov", ".mp4"]


class TestHelpEpilogs:
    def test_vendor_qc_epilog_mentions_profile_system(self):
        assert "--profiles-dir" in VENDOR_QC_EPILOG
        assert "v210_quad_ntsc" in VENDOR_QC_EPILOG

    def test_donor_triage_epilog_mentions_no_policy(self):
        assert "No MediaConch policy" in DONOR_TRIAGE_EPILOG
