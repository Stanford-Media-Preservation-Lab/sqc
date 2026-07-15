"""ffmpeg null-muxer pass — essence-level error detection.

Stress-tests actual decodability of the essence (catches bitrot/essence
glitches that metadata-only checks miss entirely). Run in two passes:
  1. Permissive (no -xerror): captures the full warning/error log.
  2. Strict (-xerror): exits non-zero on the first hard error — a clean
     pass/fail signal, but a full decode, so it's not free on large files
     (see modes/vendor_qc.py and modes/donor_triage.py for the per-mode
     default: on for donor-triage, opt-in for vendor-qc).
Always run at -loglevel warning — the default level misses many interesting
non-fatal codec complaints.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from sqc.report.schema import CheckResult

TIMEOUT_NULL_PASS = None  # a full decode of a large uncompressed master can take a while


def run_null_pass(path: Path, strict: bool, extra_input_args: Optional[list[str]] = None) -> tuple[bool, str]:
    """Decode path through the null muxer. Returns (success, stderr_text).

    extra_input_args are inserted before -i (e.g. ["-apply_cropping", "0"] for
    the AJA clap-atom capture quirk — see policy.py's PolicyProfile.capture_quirks).
    """
    cmd = ["ffmpeg", "-y", "-v", "warning"]
    if extra_input_args:
        cmd += extra_input_args
    if strict:
        cmd += ["-xerror"]
    cmd += ["-i", str(path), "-f", "null", "-"]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_NULL_PASS)
    return r.returncode == 0, r.stderr.strip()


def run_essence_checks(path: Path, extra_input_args: Optional[list[str]] = None) -> list[CheckResult]:
    """Run both passes and translate them into CheckResults.

    The permissive pass always runs (its full warning log has diagnostic
    value even when it doesn't fail); the strict pass gives the actual
    pass/fail verdict. Note: dropout-concealment/head-clog artifacts leave
    the file structurally decodable — a null pass will not catch these; it
    only catches genuine bitrot/essence corruption that produces a real
    decode error.
    """
    results = []
    permissive_ok, permissive_stderr = run_null_pass(path, strict=False, extra_input_args=extra_input_args)
    if permissive_stderr:
        results.append(CheckResult(
            "essence_null_pass_permissive", "INFO" if permissive_ok else "WARN",
            f"ffmpeg null pass warnings: {permissive_stderr[:300]}",
        ))
    else:
        results.append(CheckResult("essence_null_pass_permissive", "PASS", "No decode warnings"))

    strict_ok, strict_stderr = run_null_pass(path, strict=True, extra_input_args=extra_input_args)
    if strict_ok:
        results.append(CheckResult("essence_null_pass_strict", "PASS", "Clean decode, no hard errors"))
    else:
        results.append(CheckResult(
            "essence_null_pass_strict", "FAIL",
            f"Decode failed under -xerror: {strict_stderr[:300]}",
        ))
    return results
