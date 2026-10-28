"""sqc CLI: argparse subcommands (vendor-qc, donor-triage), dispatch.

Mirrors srw's pattern: add_subparsers(dest="command", required=True), each
subcommand has its own add_<mode>_arguments(parser) function and
.set_defaults(func=...), and a Config dataclass is built once from parsed
args and threaded through instead of passing args around.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from sqc import deps
from sqc.batch import run_batch
from sqc.config import (
    DEFAULT_DONOR_TRIAGE_EXTENSIONS,
    BatchConfig,
    DonorTriageConfig,
    VendorQCConfig,
)
from sqc._version import __version__
from sqc.intake import discover_files
from sqc.logs import setup_logging
from sqc.modes import donor_triage, vendor_qc
from sqc.policy import load_profile
from sqc.report.csv_summary import write_csv



def add_shared_arguments(parser: argparse.ArgumentParser, default_extensions) -> None:
    parser.add_argument(
        "input", type=Path,
        help="File or directory to scan (directory is scanned recursively)",
    )
    # nargs="+" greedily consumes following tokens, including the positional
    # `input` if --extensions is given before it (e.g. `--extensions .mov
    # input_dir` reads "input_dir" as a third extension). Put `input` first
    # when using --extensions: `sqc <mode> input_dir --extensions .mov .mp4`.
    parser.add_argument("--extensions", nargs="+", default=default_extensions, metavar="EXT")
    parser.add_argument("--report-dir", type=Path, default=Path("./sqc_reports"), metavar="DIR")
    parser.add_argument("--csv", type=Path, default=None, metavar="FILE")
    parser.add_argument("--log-file", type=Path, default=None, metavar="FILE")
    parser.add_argument(
        "--workers", type=int, default=None, metavar="N",
        help=(
            "Parallel worker processes (default: one per file). This workload is "
            "typically I/O-bound — measure your machine's real ceiling with "
            "iostat/iotop rather than assuming a number from CPU count."
        ),
    )
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument("--resume", dest="resume", action="store_true", default=True,
        help="Skip files with an existing, non-TOOL_FAILURE JSON report (default: on)")
    resume_group.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument(
        "--full", action="store_true",
        help="Include frame-level packet timing analysis (slower; needed for VFR classification)",
    )


def add_vendor_qc_arguments(parser: argparse.ArgumentParser) -> None:
    add_shared_arguments(parser, default_extensions=None)  # resolved from the profile if not given
    parser.add_argument("--profile", required=True, metavar="NAME_OR_PATH",
        help="Bundled profile name (looked up in --profiles-dir) or a path to a standalone .toml file")
    parser.add_argument("--profiles-dir", type=Path, default=Path("./profiles"), metavar="DIR")
    parser.add_argument("--mediaconch-dir", type=Path, default=Path("./MediaConch"), metavar="DIR")
    parser.add_argument(
        "--strict-decode-check", action="store_true", default=False,
        help=(
            "Also run the ffmpeg null-pass essence decode check (off by default for "
            "vendor-qc — MediaConch + crosscheck already carry most of the diagnostic "
            "weight, and a full decode of a large uncompressed master isn't free)"
        ),
    )
    parser.add_argument("--av-duration-threshold", type=float, default=None, metavar="SECONDS",
        dest="av_duration_threshold_s")


def add_donor_triage_arguments(parser: argparse.ArgumentParser) -> None:
    add_shared_arguments(parser, default_extensions=list(DEFAULT_DONOR_TRIAGE_EXTENSIONS))
    parser.add_argument(
        "--strict-decode-check", dest="strict_decode_check", action="store_true", default=True,
        help="ffmpeg null-pass essence decode check (default: on — this mode's main "
             "defense against corruption when there's no spec to check metadata against)",
    )
    parser.add_argument("--no-strict-decode-check", dest="strict_decode_check", action="store_false")


def _build_batch_config(args: argparse.Namespace, extensions: list[str]) -> BatchConfig:
    report_dir = args.report_dir
    csv_path = args.csv or (report_dir / "summary.csv")
    log_file = args.log_file or Path(
        f"sqc_{args.command.replace('-', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    return BatchConfig(
        input_path=args.input, extensions=extensions, report_dir=report_dir,
        csv_path=csv_path, log_file=log_file, workers=args.workers,
        resume=args.resume, full=args.full,
    )


def _summarize(reports, log, csv_path: Path) -> int:
    counts: dict[str, int] = {}
    for r in reports:
        counts[r.overall_status] = counts.get(r.overall_status, 0) + 1

    log.info("=" * 60)
    log.info("SUMMARY")
    log.info(f"  Files processed: {len(reports)}")
    for status in ("FAIL", "WARN", "PASS", "SKIP", "TOOL_FAILURE"):
        if counts.get(status):
            log.info(f"    {status:<12}: {counts[status]}")
    log.info(f"  CSV summary: {csv_path}")
    log.info("=" * 60)
    return 1 if counts.get("FAIL") or counts.get("TOOL_FAILURE") else 0


def run_vendor_qc(args: argparse.Namespace) -> int:
    extensions = args.extensions
    if not extensions:
        try:
            profile = load_profile(args.profile, args.profiles_dir, args.mediaconch_dir)
        except (FileNotFoundError, ValueError) as e:
            sys.exit(f"ERROR: {e}")
        extensions = profile.container_extensions

    batch = _build_batch_config(args, extensions)
    log = setup_logging(batch.log_file)

    layers = ["crosscheck", "mediaconch_policy", "frame_timing"]
    if args.strict_decode_check:
        layers.append("ffmpeg_null")
    deps.check_dependencies(layers)

    try:
        files = discover_files(args.input, batch.extensions)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")

    log.info(f"sqc vendor-qc — profile={args.profile!r}, {len(files)} file(s) discovered")

    config = VendorQCConfig(
        batch=batch,
        profile_name=args.profile,
        profiles_dir=args.profiles_dir,
        mediaconch_dir=args.mediaconch_dir,
        strict_decode_check=args.strict_decode_check,
        av_duration_threshold_s=args.av_duration_threshold_s,
    )

    reports = run_batch(files, batch, "vendor_qc", vendor_qc.process_file, config, log)
    write_csv(reports, batch.csv_path, mode="vendor_qc")
    return _summarize(reports, log, batch.csv_path)


def run_donor_triage(args: argparse.Namespace) -> int:
    batch = _build_batch_config(args, args.extensions)
    log = setup_logging(batch.log_file)

    layers = ["crosscheck", "frame_timing"]
    if args.strict_decode_check:
        layers.append("ffmpeg_null")
    deps.check_dependencies(layers)

    try:
        files = discover_files(args.input, batch.extensions)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")

    log.info(f"sqc donor-triage — {len(files)} file(s) discovered")

    config = DonorTriageConfig(batch=batch, strict_decode_check=args.strict_decode_check)
    reports = run_batch(files, batch, "donor_triage", donor_triage.process_file, config, log)
    write_csv(reports, batch.csv_path, mode="donor_triage")
    return _summarize(reports, log, batch.csv_path)


TOP_LEVEL_EPILOG = """\
sqc -- Stanford Media Preservation Lab QC tool

Two modes:
  vendor-qc      Spec conformance against a pluggable policy profile, for
                 outsourced vendor tape digitization deliveries (2" Quad,
                 1" Type C, etc.) that must match a written technical spec.
  donor-triage   Well-formedness only, no spec -- for donor collections and
                 institutional-partner collection addenda (including raw
                 camera cards). Just tells you which files are broken.

See MANUAL.md for the full reference, or `sqc <mode> --help` for that
mode's flags.
"""

VENDOR_QC_EPILOG = """\
Runs the shared cross-tool integrity engine (MediaInfo/ffprobe/MediaTrace/
ExifTool) plus a MediaConch policy check and the full VFR taxonomy
(timescale rounding / VTR spin-down / genuine dropped frames) against a
named policy profile. Profiles live in --profiles-dir (default ./profiles)
as TOML files; see profiles/v210_quad_ntsc.toml for the bundled reference
profile.

Example:
  sqc vendor-qc --profile v210_quad_ntsc --full /Volumes/Vendor_Delivery
"""

DONOR_TRIAGE_EPILOG = """\
Runs the shared cross-tool integrity engine plus an ffmpeg null-muxer
decode check (on by default here -- this mode's main defense against
essence-level corruption when there's no spec to check metadata against).
No MediaConch policy, no bit-depth-fraud detection (vendor-qc-only). VFR is
detected but never classified as spin-down-vs-drops the way vendor-qc does,
since donor material may have legitimately intentional VFR.

Example:
  sqc donor-triage --full /Volumes/Donor_Collection
"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqc",
        description="SMPL QC tool: vendor-qc (spec conformance) and donor-triage (well-formedness) modes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=TOP_LEVEL_EPILOG,
    )
    parser.add_argument("--version", action="version", version=f"sqc {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    vendor_qc_parser = subparsers.add_parser(
        "vendor-qc", help="Spec conformance against a policy profile",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=VENDOR_QC_EPILOG,
    )
    add_vendor_qc_arguments(vendor_qc_parser)
    vendor_qc_parser.set_defaults(func=run_vendor_qc)

    donor_triage_parser = subparsers.add_parser(
        "donor-triage", help="Well-formedness check, no spec required",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=DONOR_TRIAGE_EPILOG,
    )
    add_donor_triage_arguments(donor_triage_parser)
    donor_triage_parser.set_defaults(func=run_donor_triage)

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
