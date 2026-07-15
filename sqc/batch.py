"""Batch orchestration: ProcessPoolExecutor, resume, per-file failure isolation.

Uses ProcessPoolExecutor (not srw.batch's ThreadPoolExecutor) because sqc
dispatches per-file tool calls from within a single Python process — real
parallelism across files needs a process pool, unlike srw.batch which just
launches whole `srw run` subprocesses (already separate OS processes, so
threads suffice there).

Parallelism default follows the lab's standing rule: never guess a "safe"
concurrency number from CPU count. `--workers` defaults to None, which means
"one worker slot per file" (mirrors srw.batch's own
`max_workers = args.max_parallel or len(jobs)` pattern) — the real per-machine
ceiling is I/O-bound and must be measured with iostat/iotop, not assumed.
"""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from tqdm import tqdm

from sqc.config import BatchConfig
from sqc.report.schema import FileReport
from sqc.report.writer import load_json_report, should_skip_for_resume, write_json_report


def _run_worker_safe(worker_fn: Callable, path: Path, mode: str, mode_config) -> FileReport:
    """Runs in the child process. Wraps the entire worker body so one bad
    file (subprocess timeout, missing binary, unexpected exception) never
    halts the batch — it's captured as TOOL_FAILURE instead of raising."""
    try:
        return worker_fn(path, mode_config)
    except Exception as e:
        return FileReport(path=path, mode=mode, overall_status="TOOL_FAILURE", error=str(e))


def run_batch(
    files: list[Path],
    batch: BatchConfig,
    mode: str,
    worker_fn: Callable,
    mode_config,
    log: logging.Logger,
) -> list[FileReport]:
    to_process: list[Path] = []
    results: list[FileReport] = []

    for f in files:
        if batch.resume and should_skip_for_resume(batch.report_dir, f):
            existing = load_json_report(batch.report_dir, f)
            results.append(FileReport.from_json_dict(existing, f))
        else:
            to_process.append(f)

    log.info(
        f"{len(files)} file(s) found; {len(results)} already complete (resume), "
        f"{len(to_process)} to process"
    )

    if not to_process:
        return results

    max_workers = batch.workers or len(to_process)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run_worker_safe, worker_fn, f, mode, mode_config): f
            for f in to_process
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"sqc {mode}"):
            f = futures[future]
            report = future.result()  # _run_worker_safe never raises
            results.append(report)
            write_json_report(report, batch.report_dir)
            for c in report.checks:
                level = {
                    "FAIL": logging.ERROR, "TOOL_FAILURE": logging.ERROR,
                    "WARN": logging.WARNING,
                }.get(c.status, logging.DEBUG)
                log.log(level, f"{f.name}: {c}")
            log.info(f"{f.name}: {report.overall_status}")

    return results
