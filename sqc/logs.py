"""Stdlib logging setup.

sqc uses Python's logging module with real levels rather than the hand-rolled
text-log convention used by srw/vdg. Those tools narrate a linear, resumable
step sequence and their resume system depends on re-scanning log text for
"Step N" success markers. sqc has no such need — resume is decided by whether
a per-file JSON report already exists (see report/writer.py), not by parsing
log lines — so structured levels that map directly onto CheckResult severities
(FAIL->ERROR, WARN->WARNING, PASS/INFO->DEBUG/INFO) are a better fit.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(log_path: Path, logger_name: str = "sqc") -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger(logger_name)
    log.setLevel(logging.DEBUG)
    log.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)

    # Console: WARN/FAIL only, for clean output during a large batch run.
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    log.addHandler(ch)

    # Also echo INFO to stdout so progress is visible without cluttering with DEBUG.
    class InfoFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.levelno == logging.INFO

    ih = logging.StreamHandler(sys.stdout)
    ih.setLevel(logging.INFO)
    ih.setFormatter(fmt)
    ih.addFilter(InfoFilter())
    log.addHandler(ih)

    return log


def log_check_result(log: logging.Logger, check) -> None:
    """Log a CheckResult at the level matching its status."""
    level = {
        "FAIL": logging.ERROR,
        "TOOL_FAILURE": logging.ERROR,
        "WARN": logging.WARNING,
        "PASS": logging.DEBUG,
        "INFO": logging.DEBUG,
        "SKIP": logging.DEBUG,
    }.get(check.status, logging.DEBUG)
    log.log(level, str(check))
