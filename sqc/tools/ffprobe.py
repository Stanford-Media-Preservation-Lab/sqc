"""ffprobe subprocess wrapper.

Adapted from smpl_qc_v210.py's probe_file()/get_packet_durations() — those
functions are proven to work (get_packet_durations reads the QuickTime
stts/stsc index tables, no pixel decoding, fast even on large uncompressed
files) so the logic is carried over essentially unchanged rather than
reinvented.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

TIMEOUT_PROBE = 120  # seconds
TIMEOUT_PACKETS = None  # no limit; large files still need time for a full packet read


def probe_file(path: Path) -> tuple[dict, str]:
    """Run ffprobe -show_format -show_streams. Returns (json_data, stderr_text).

    Raises RuntimeError if ffprobe returns non-zero or produces unparseable JSON.
    """
    cmd = [
        "ffprobe", "-v", "warning",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_PROBE)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe exited {r.returncode}: {r.stderr.strip()[:400]}")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe JSON parse error: {e}")
    return data, r.stderr.strip()


def get_packet_durations(path: Path) -> list[float]:
    """Extract per-frame video packet duration_time via ffprobe -show_packets.

    For QuickTime MOV this reads the stts/stsc tables from the moov atom —
    no decoding, fast even on large uncompressed files.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_packets",
        "-print_format", "json",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_PACKETS)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe -show_packets returned {r.returncode}: {r.stderr.strip()[:400]}")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe packet JSON parse error: {e}")

    durations = []
    for pkt in data.get("packets", []):
        dt = pkt.get("duration_time")
        if dt and dt not in ("N/A", ""):
            try:
                durations.append(float(dt))
            except ValueError:
                pass
    return durations
