"""Vendor-qc policy profile loading.

A profile generalizes smpl_qc_v210.py's POLICY_DEFAULTS dict (expected codec/
resolution/fps/timescale/bit-depth/field-order/audio spec, plus VFR-taxonomy
thresholds) into a TOML file, so a new vendor format (1" Type C, outsourced
1/2" EIAJ) is "add a .toml + .xml," not new Python code.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PolicyProfile:
    name: str
    description: str
    container_extensions: list[str]
    mediaconch_policy: Path
    video: dict
    audio: dict
    thresholds: dict
    capture_quirks: dict

    def frame_timing_thresholds(self) -> dict:
        return {
            "spin_down_zone": self.thresholds.get("spin_down_zone", 0.97),
            "frame_anomaly_low_ratio": self.thresholds.get("frame_anomaly_low_ratio", 0.5),
            "frame_anomaly_high_ratio": self.thresholds.get("frame_anomaly_high_ratio", 1.5),
        }


REQUIRED_SECTIONS = ["profile", "video", "audio", "thresholds"]
REQUIRED_PROFILE_KEYS = ["name", "description", "container_extensions", "mediaconch_policy"]


def resolve_profile_path(name_or_path: str, profiles_dir: Path) -> Path:
    candidate = Path(name_or_path)
    if candidate.is_file():
        return candidate
    if candidate.suffix != ".toml":
        candidate = Path(f"{name_or_path}.toml")
    resolved = profiles_dir / candidate
    if not resolved.is_file():
        raise FileNotFoundError(
            f"Policy profile {name_or_path!r} not found — looked for {resolved} "
            f"(and as a direct path). Available profiles in {profiles_dir}: "
            f"{[p.stem for p in profiles_dir.glob('*.toml')] if profiles_dir.is_dir() else '(directory not found)'}"
        )
    return resolved


def load_profile(name_or_path: str, profiles_dir: Path, mediaconch_dir: Path) -> PolicyProfile:
    path = resolve_profile_path(name_or_path, profiles_dir)
    with open(path, "rb") as f:
        data = tomllib.load(f)

    missing_sections = [s for s in REQUIRED_SECTIONS if s not in data]
    if missing_sections:
        raise ValueError(f"Policy profile {path}: missing section(s) {missing_sections}")

    profile_section = data["profile"]
    missing_keys = [k for k in REQUIRED_PROFILE_KEYS if k not in profile_section]
    if missing_keys:
        raise ValueError(f"Policy profile {path}: [profile] missing key(s) {missing_keys}")

    mc_policy_raw = Path(profile_section["mediaconch_policy"])
    mediaconch_policy = mc_policy_raw if mc_policy_raw.is_absolute() else mediaconch_dir / mc_policy_raw

    return PolicyProfile(
        name=profile_section["name"],
        description=profile_section["description"],
        container_extensions=profile_section["container_extensions"],
        mediaconch_policy=mediaconch_policy,
        video=data.get("video", {}),
        audio=data.get("audio", {}),
        thresholds=data.get("thresholds", {}),
        capture_quirks=data.get("capture_quirks", {}),
    )
