from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "system_core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from chunk_workers import MAX_WORKERS, resolve_workers, run_jobs
from pipeline import chunk_eta, rows_from_chunk_cache, run_chunk_jobs


class ResolveWorkersTests(unittest.TestCase):
    def test_bad_values_fall_back_to_the_default(self) -> None:
        self.assertEqual(resolve_workers(None), 4)
        self.assertEqual(resolve_workers(""), 4)
        self.assertEqual(resolve_workers("nonsense"), 4)

    def test_counts_are_clamped_to_a_runnable_range(self) -> None:
        self.assertEqual(resolve_workers(0), 1)
        self.assertEqual(resolve_workers(-5), 1)
        self.assertEqual(resolve_workers("8"), 8)
        self.assertEqual(resolve_workers(9999), MAX_WORKERS)


class RunJobsTests(unittest.TestCase):
    def test_jobs_really_run_side_by_side(self) -> None:
        # The barrier only clears if all four jobs are in flight at once; a
        # sequential runner would deadlock here and trip the timeout.
        barrier = threading.Barrier(4, timeout=10)
        done: list[int] = []
        lock = threading.Lock()

        def work(job: int) -> None:
            barrier.wait()
            with lock:
                done.append(job)

        run_jobs([1, 2, 3, 4], work, workers=4)
        self.assertEqual(sorted(done), [1, 2, 3, 4])

    def test_single_worker_stays_sequential(self) -> None:
        active = 0
        peak = 0
        lock = threading.Lock()

        def work(_job: int) -> None:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1

        run_jobs(list(range(5)), work, workers=1)
        self.assertEqual(peak, 1)

    def test_failure_is_raised_but_running_work_still_finishes(self) -> None:
        finished: list[int] = []
        lock = threading.Lock()

        def work(job: int) -> None:
            if job == 0:
                raise RuntimeError("chunk 0 failed")
            time.sleep(0.05)
            with lock:
                finished.append(job)

        with self.assertRaisesRegex(RuntimeError, "chunk 0 failed"):
            run_jobs([0, 1, 2], work, workers=3)

        # Jobs already in flight are paid for, so they are allowed to complete.
        self.assertEqual(sorted(finished), [1, 2])


class RunChunkJobsTests(unittest.TestCase):
    def _pairs(self, count: int) -> list[tuple[str, str]]:
        return [(f"overlap{i}", f"chunk{i}") for i in range(1, count + 1)]

    def test_rows_keep_chunk_order_even_when_later_chunks_finish_first(self) -> None:
        def call(index: int, _overlap: str, _chunk: str):
            # Reverse the completion order: chunk 3 returns first, chunk 1 last.
            time.sleep(0.05 * (4 - index))
            return {"rows": [{"id": f"row{index}"}]}, {"input_tokens": index}, "default"

        chunk_cache: dict[str, object] = {}
        run_chunk_jobs(
            self._pairs(3),
            label="Test",
            workers=3,
            chunk_cache=chunk_cache,
            call=call,
            extract_rows=lambda obj: obj["rows"],
        )

        self.assertEqual(sorted(chunk_cache), ["1", "2", "3"])
        self.assertEqual([row["id"] for row in rows_from_chunk_cache(chunk_cache)], ["row1", "row2", "row3"])

    def test_cached_chunks_are_never_recalled(self) -> None:
        called: list[int] = []

        def call(index: int, _overlap: str, _chunk: str):
            called.append(index)
            return {"rows": []}, {}, "default"

        chunk_cache = {"2": {"index": 2, "rows": [{"id": "cached"}], "usage": {}, "service_tier": "default"}}
        run_chunk_jobs(
            self._pairs(3),
            label="Test",
            workers=2,
            chunk_cache=chunk_cache,
            call=call,
            extract_rows=lambda obj: obj["rows"],
        )

        self.assertEqual(sorted(called), [1, 3])
        self.assertEqual([row["id"] for row in rows_from_chunk_cache(chunk_cache)], ["cached"])

    def test_progress_is_persisted_after_every_finished_chunk(self) -> None:
        snapshots: list[int] = []

        def call(index: int, _overlap: str, _chunk: str):
            return {"rows": [{"id": index}]}, {}, "default"

        run_chunk_jobs(
            self._pairs(4),
            label="Test",
            workers=4,
            chunk_cache={},
            call=call,
            extract_rows=lambda obj: obj["rows"],
            persist=lambda snapshot: snapshots.append(len(snapshot)),
        )

        # One write per chunk, and the last one sees the full set.
        self.assertEqual(len(snapshots), 4)
        self.assertEqual(max(snapshots), 4)

    def test_eta_accounts_for_parallel_lanes(self) -> None:
        durations = [60.0, 60.0]
        self.assertEqual(chunk_eta(durations, 10, 2), "08:00")
        self.assertEqual(chunk_eta(durations, 10, 2, workers=8), "01:00")


if __name__ == "__main__":
    unittest.main()
