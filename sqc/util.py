"""Small parsing helpers shared across analysis/mode modules."""

from __future__ import annotations

from typing import Optional


def to_float(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def to_int(x) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def parse_rational(s: str) -> Optional[tuple]:
    """'30000/1001' -> (30000, 1001). None on failure or zero denominator."""
    if not s or "/" not in s:
        return None
    try:
        n, d = s.split("/", 1)
        return (int(n), int(d)) if int(d) != 0 else None
    except ValueError:
        return None
