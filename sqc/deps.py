"""External tool dependency checks.

Mirrors srw's STEP_DEPENDENCIES / tools_needed_for_range() / check_dependencies()
pattern, keyed by analysis layer instead of numbered step. Install hints are
OS-aware (Homebrew on macOS, apt on Ubuntu) since sqc, like vdg, targets both
platforms — unlike srw which is Ubuntu-only.
"""

from __future__ import annotations

import shutil
import sys

# tool binary name -> (homebrew package, apt package)
# Note: MediaTrace has no standalone binary; it's `mediaconch --Mediatrace`, so
# it rides on the "mediaconch" binary check, not its own entry.
TOOL_PACKAGES = {
    "mediainfo": ("mediainfo", "mediainfo"),
    "ffprobe": ("ffmpeg", "ffmpeg"),
    "ffmpeg": ("ffmpeg", "ffmpeg"),
    "mediaconch": ("mediaconch", "mediaconch"),
    "exiftool": ("exiftool", "libimage-exiftool-perl"),
}

# Which tools each analysis layer needs.
LAYER_DEPENDENCIES = {
    "crosscheck": ["mediainfo", "ffprobe", "mediaconch", "exiftool"],
    "mediaconch_policy": ["mediaconch"],
    "ffmpeg_null": ["ffmpeg"],
    "frame_timing": ["ffprobe"],
}


def tools_needed_for_layers(layers: list[str]) -> set[str]:
    tools: set[str] = set()
    for layer in layers:
        tools.update(LAYER_DEPENDENCIES.get(layer, []))
    return tools


def _install_hint(tool: str) -> str:
    brew_pkg, apt_pkg = TOOL_PACKAGES.get(tool, (tool, tool))
    if sys.platform == "darwin":
        return f"brew install {brew_pkg}"
    return f"sudo apt install {apt_pkg}"


def check_dependencies(layers: list[str]) -> None:
    """Exit with a clear message if any tool needed by the given layers is missing."""
    missing = []
    for tool in sorted(tools_needed_for_layers(layers)):
        if shutil.which(tool) is None:
            missing.append(tool)

    if missing:
        lines = ["FATAL ERROR: required tool(s) not found on PATH:"]
        for tool in missing:
            lines.append(f"  {tool}  ->  {_install_hint(tool)}")
        sys.exit("\n".join(lines))
