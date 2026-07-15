"""MediaInfo subprocess wrapper — the "reported metadata" lens."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

TIMEOUT_MEDIAINFO = 120


def run_mediainfo(path: Path) -> dict:
    """Run mediainfo in full JSON output mode. Returns the parsed JSON dict.

    Raises RuntimeError on nonzero exit or unparseable output.
    """
    cmd = ["mediainfo", "--Output=JSON", "--Full", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_MEDIAINFO)
    if r.returncode != 0:
        raise RuntimeError(f"mediainfo exited {r.returncode}: {r.stderr.strip()[:400]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"mediainfo JSON parse error: {e}")
