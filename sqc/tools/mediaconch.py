"""MediaConch policy-check wrapper.

Ported from srw/srw/cli.py's run_mediaconch()/validate_files_against_policy(),
which is a proven, production-hardened pattern (fresh auto-cleaned HOME per
call so MediaConch's own config/cache doesn't collide across concurrent jobs;
batched CSV-format calls instead of one subprocess per file, to stay well
under ARG_MAX and avoid spawning one process per file across a large batch).
"""

from __future__ import annotations

import csv
import io
import os
import subprocess
import tempfile
from pathlib import Path

DEFAULT_MEDIACONCH_BATCH_SIZE = 2000


def run_mediaconch(policy_path: Path, files: list[Path], csv_format: bool = False) -> subprocess.CompletedProcess:
    """Run mediaconch once against a list of files, with an isolated HOME.

    MediaConch reads/writes user-specific config/cache under HOME; a fresh,
    auto-cleaned temp HOME per call means concurrent sqc batch workers never
    collide on that state.
    """
    args = ["mediaconch", "-p", str(policy_path)]
    if csv_format:
        args.append("-fc")
    args.extend(str(f) for f in files)
    with tempfile.TemporaryDirectory(prefix="sqc-mediaconch-home-") as home_dir:
        env = {**os.environ, "HOME": home_dir}
        return subprocess.run(args, capture_output=True, text=True, env=env)


def validate_files_against_policy(
    files: list[Path],
    policy_path: Path,
    batch_size: int = DEFAULT_MEDIACONCH_BATCH_SIZE,
):
    """Validate files against a MediaConch policy in batches, yielding (file, is_valid).

    Yields lazily in original file order, one batch of subprocess work at a time.
    """
    for i in range(0, len(files), batch_size):
        chunk = files[i : i + batch_size]
        result = run_mediaconch(policy_path, chunk, csv_format=True)
        passed = set()
        reader = csv.DictReader(io.StringIO(result.stdout))
        for row in reader:
            if row.get("overall") == "pass":
                passed.add(row["filename"])
        for f in chunk:
            yield f, str(f) in passed


def get_policy_detail(policy_path: Path, file: Path) -> str:
    """Single-file, human-readable MediaConch report (used when a file fails
    the batched CSV check and full detail is wanted for the report/log)."""
    result = run_mediaconch(policy_path, [file], csv_format=False)
    return result.stdout.strip() or result.stderr.strip()
