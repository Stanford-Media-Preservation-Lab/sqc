"""MediaTrace wrapper — the "binary anatomy" lens (where atoms/boxes physically sit).

MediaTrace has no standalone binary; it's `mediaconch --Mediatrace` (confirmed
locally: `mediaconch --help` lists it as `--Mediatrace, -mt`). Its output is
always XML regardless of any `--Format=`/-f* flag (those flags only affect
policy-check reports, not the trace) — confirmed empirically against a real
.mov file locally, so this wrapper parses XML, not JSON.
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

TIMEOUT_MEDIATRACE = 300  # trace can be slower than a plain probe on large files


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _element_to_dict(elem: ET.Element) -> dict:
    """Minimal recursive XML->dict conversion (stdlib only, no new dependency).

    Repeated child tags collapse into a list; leaf elements keep their text
    and attributes. Good enough to grep atom/box names and offsets out of a
    MediaTrace tree without needing a full schema-aware parser.
    """
    node: dict = {f"@{k}": v for k, v in elem.attrib.items()}
    children: dict = {}
    for child in elem:
        tag = _strip_ns(child.tag)
        value = _element_to_dict(child)
        if tag in children:
            if not isinstance(children[tag], list):
                children[tag] = [children[tag]]
            children[tag].append(value)
        else:
            children[tag] = value
    if children:
        node.update(children)
    elif elem.text and elem.text.strip():
        return elem.text.strip()
    return node


def run_mediatrace(path: Path) -> dict:
    """Run `mediaconch -mt -fx <path>` and return a nested dict of the trace.

    Raises RuntimeError on nonzero exit or unparseable XML.
    """
    cmd = ["mediaconch", "-mt", "-fx", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_MEDIATRACE)
    if r.returncode != 0:
        raise RuntimeError(f"mediaconch -mt exited {r.returncode}: {r.stderr.strip()[:400]}")
    try:
        root = ET.fromstring(r.stdout)
    except ET.ParseError as e:
        raise RuntimeError(f"MediaTrace XML parse error: {e}")
    return {_strip_ns(root.tag): _element_to_dict(root)}
