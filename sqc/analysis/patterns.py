"""Known pattern library — recurring anomaly signatures.

A plain registry list, not a plugin/metaclass system: adding a new recognized
pattern (a new vendor format surfaces a new recurring artifact) is one new
Pattern(...) entry, no engine changes. Detectors in analysis/crosscheck.py and
analysis/frame_timing.py set CheckResult.pattern_id when they match one of
these; mode orchestrators (modes/vendor_qc.py, modes/donor_triage.py) resolve
severity via get_pattern() at report-assembly time, so vendor-qc-vs-donor-triage
severity divergence is a table lookup, not duplicated branching logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Pattern:
    pattern_id: str
    default_severity: str  # WARN | FAIL — used by vendor-qc
    triage_severity: Optional[str]  # override for donor-triage; None = same as default_severity
    description: str
    cause: str
    remediation: str
    mode_scope: str  # "both" | "vendor_qc"

    def severity_for_mode(self, mode: str) -> str:
        if mode == "donor_triage" and self.triage_severity is not None:
            return self.triage_severity
        return self.default_severity


PATTERN_REGISTRY: list[Pattern] = [
    Pattern(
        "VFR_TAIL_ARTIFACT", "WARN", None,
        "VFR confined to the last frames only",
        "Digitization capture tail artifact (VTR head spin-down); common with "
        "2\" Quad and other tape formats",
        "Trim trailing anomalous frames during transcode; verify audio duration integrity",
        mode_scope="both",
    ),
    Pattern(
        "VFR_TIMEBASE_ROUNDING", "WARN", None,
        "Alternating 1001/1002 tick pattern throughout, no large anomalies",
        "Benign QuickTime muxer artifact: video track timescale not a multiple "
        "of 30000 forces alternating tick values at 29.97fps",
        "No action required for playback; lossless remux with "
        "-video_track_timescale 30000 -c copy if a clean CFR file is needed",
        mode_scope="both",
    ),
    Pattern(
        "VFR_GENUINE_DROPS", "FAIL", "WARN",
        "Anomalous frame durations distributed throughout the file, not tail-only",
        "Dropped frames during tape capture",
        "Return to vendor / re-digitize (vendor-qc); for donor-triage this is "
        "informational only — may reflect intentional VFR capture rather than a defect",
        mode_scope="both",
    ),
    Pattern(
        "FAKE_10BIT_LSHIFT", "FAIL", "WARN",
        "LSB distribution consistent with an 8-bit source left-shifted to 10-bit",
        "8-bit source naively promoted to 10-bit by the capture/transcode chain",
        "Return to vendor; request genuine 10-bit capture",
        mode_scope="vendor_qc",  # detector deferred to v1.1 — see analysis/bitdepth.py
    ),
    Pattern(
        "EXTENSION_FORMAT_MISMATCH", "WARN", None,
        "File extension does not match the detected container format",
        "Renamed file, or incorrect extension assigned during a vendor/donor workflow",
        "Correct the extension; flag for manual review before accessioning",
        mode_scope="both",
    ),
    Pattern(
        "CONTAINER_CODEC_MISMATCH", "FAIL", None,
        "Codec is not valid for the declared container",
        "Incorrect mux — a \"Frankenstein\" file",
        "Remux to the correct container or re-encode",
        mode_scope="both",
    ),
    Pattern(
        "MISSING_MOOV_ATOM", "FAIL", None,
        "No moov atom found",
        "Incomplete or aborted write; the file was never finalized",
        "Attempt untrunc or similar recovery; flag as unrecoverable if unsuccessful",
        mode_scope="both",
    ),
    Pattern(
        "STREAM_DURATION_MISMATCH", "WARN", None,
        "Audio and video stream durations differ beyond threshold",
        "Truncation, mux error, or capture issue",
        "Investigate; trim or pad depending on magnitude",
        mode_scope="both",
    ),
    Pattern(
        "MULTI_VIDEO_STREAM", "WARN", None,
        "Multiple video streams present; one or more may be empty",
        "Consumer tool artifact, or an accidental duplicate stream",
        "Examine each stream; remux keeping only the valid one",
        mode_scope="both",
    ),
]

_BY_ID = {p.pattern_id: p for p in PATTERN_REGISTRY}


def get_pattern(pattern_id: str) -> Pattern:
    return _BY_ID[pattern_id]


def patterns_for_mode(mode: str) -> list[Pattern]:
    return [p for p in PATTERN_REGISTRY if p.mode_scope == "both" or p.mode_scope == mode]
