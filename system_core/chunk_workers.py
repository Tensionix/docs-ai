#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Concurrent chunk execution shared by the audit pipeline and the task runner.

Chunks of a document are independent of each other: overlap is already baked into
each chunk's text, so nothing here has to preserve call order. Results are keyed by
chunk index by the callers, which keeps output deterministic no matter which chunk
finishes first.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Sequence, TypeVar

DEFAULT_WORKERS = 4
MAX_WORKERS = 32

T = TypeVar("T")


def resolve_workers(value: Any, *, default: int = DEFAULT_WORKERS) -> int:
    """Clamp a GUI/CLI worker count to a value the process can actually run."""
    try:
        workers = int(value)
    except (TypeError, ValueError):
        workers = default
    if workers < 1:
        return 1
    return min(workers, MAX_WORKERS)


def run_jobs(jobs: Sequence[T], worker: Callable[[T], None], *, workers: int) -> None:
    """Run `worker` over every job, at most `workers` at a time.

    A failing job does not kill the ones already in flight: pending jobs are
    cancelled, running ones are allowed to finish (they have already been paid for
    and their callers cache them), and the first error is raised afterwards.
    """
    if not jobs:
        return

    lanes = min(resolve_workers(workers), len(jobs))
    if lanes == 1:
        for job in jobs:
            worker(job)
        return

    with ThreadPoolExecutor(max_workers=lanes, thread_name_prefix="chunk") as pool:
        futures = [pool.submit(worker, job) for job in jobs]
        error: BaseException | None = None
        for future in as_completed(futures):
            try:
                future.result()
            except BaseException as exc:  # noqa: BLE001 - re-raised once the pool settles
                if error is None:
                    error = exc
                    for pending in futures:
                        pending.cancel()
        if error is not None:
            raise error
