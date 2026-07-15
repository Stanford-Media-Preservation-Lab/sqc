"""ExifTool wrapper — embedded metadata / encoder-provenance lens.

v1 surfaces the raw metadata dict into FileReport.exiftool_data (useful for a
human reviewing a report, and for extracting encoder version strings) but does
not build pattern-matching logic on top of it yet — deferred to a fast-follow
once real report data shows what's worth automating (see CLAUDE.md).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

TIMEOUT_EXIFTOOL = 120


def run_exiftool(path: Path) -> dict:
    """Run exiftool -json -a -G1. Returns the parsed metadata dict for the file.

    Raises RuntimeError on nonzero exit or unparseable output.
    """
    cmd = ["exiftool", "-json", "-a", "-G1", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_EXIFTOOL)
    if r.returncode != 0:
        raise RuntimeError(f"exiftool exited {r.returncode}: {r.stderr.strip()[:400]}")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"exiftool JSON parse error: {e}")
    return data[0] if data else {}
