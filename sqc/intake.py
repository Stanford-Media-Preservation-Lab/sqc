"""File discovery.

Extension is used only to decide which files to *pick up* for scanning — it is
never trusted as the actual container format. Format identification itself
happens downstream in analysis/crosscheck.py from MediaInfo's/ffprobe's own
detected format_name, so a mislabeled file still gets analyzed correctly and
an extension/format mismatch becomes a normal EXTENSION_FORMAT_MISMATCH finding
rather than a file that's silently skipped or misrouted.
"""

from __future__ import annotations

from pathlib import Path


def discover_files(input_path: Path, extensions: list[str]) -> list[Path]:
    exts = {(e if e.startswith(".") else f".{e}").lower() for e in extensions}

    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted(
            p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in exts
        )
    raise ValueError(f"{input_path!r} is not a file or directory")
