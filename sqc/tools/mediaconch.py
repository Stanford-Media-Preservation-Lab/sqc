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
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_MEDIACONCH_BATCH_SIZE = 2000


def run_mediaconch(
    policy_path: Path,
    files: list[Path],
    csv_format: bool = False,
    xml_format: bool = False,
) -> subprocess.CompletedProcess:
    """Run mediaconch once against a list of files, with an isolated HOME.

    MediaConch reads/writes user-specific config/cache under HOME; a fresh,
    auto-cleaned temp HOME per call means concurrent sqc batch workers never
    collide on that state.
    """
    args = ["mediaconch", "-p", str(policy_path)]
    if csv_format:
        args.append("-fc")
    elif xml_format:
        args.append("-fx")
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


def _collect_failing_rules(element: ET.Element, results: list[dict]) -> None:
    """Recursively collect failing <rule> elements from MediaConch -fx XML output."""
    for child in element:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        status = child.get("status", "")
        if tag == "rule":
            if status == "fail":
                # `actual` is what the file contains; expected value is in element
                # text content (the rule's operand from the policy XML).
                actual = child.get("actual", "")
                expected = (child.text or "").strip()
                results.append({
                    "name": child.get("name", "unknown rule"),
                    "actual": actual,
                    "expected": expected,
                })
        else:
            _collect_failing_rules(child, results)


def get_policy_failures(policy_path: Path, file: Path) -> list[dict]:
    """Return per-rule failures from MediaConch XML output (-fx format).

    Each dict has keys: name, actual (may be empty), expected (may be empty).
    Returns an empty list if XML parsing fails — caller should fall back to
    get_policy_detail() text output in that case.
    """
    result = run_mediaconch(policy_path, [file], xml_format=True)
    if not result.stdout.strip():
        return []
    try:
        root = ET.fromstring(result.stdout)
        failures: list[dict] = []
        _collect_failing_rules(root, failures)
        return failures
    except ET.ParseError:
        return []


def get_policy_detail(policy_path: Path, file: Path) -> str:
    """Single-file human-readable MediaConch report. Fallback when XML parsing
    fails — returns the full text output, untruncated."""
    result = run_mediaconch(policy_path, [file])
    return result.stdout.strip() or result.stderr.strip()
