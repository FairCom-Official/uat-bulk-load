"""Find the fastest FairCom worker count for the JSON insertRecords loader.

The batch-size sweep showed throughput is flat across batch sizes, which means
the bottleneck is the synchronous request/response cycle, not payload size. This
script holds the batch size fixed and varies the number of concurrent worker
threads posting insertRecords requests in parallel, to see how much headroom the
REST path has when requests overlap.

Usage:
    python3 scripts/sweep_faircom_workers.py                # default worker counts
    python3 scripts/sweep_faircom_workers.py 1 4 8 16       # custom worker counts
    BATCH=5000 python3 scripts/sweep_faircom_workers.py     # override batch size
"""
from __future__ import annotations

import os
import sys

import load_faircom
from config import FAIRCOM_BATCH_SIZE

DEFAULT_WORKER_COUNTS = [1, 2, 4, 8, 16]


def main() -> None:
    if len(sys.argv) > 1:
        worker_counts = [int(a) for a in sys.argv[1:]]
    else:
        worker_counts = DEFAULT_WORKER_COUNTS

    batch_size = int(os.environ.get("BATCH", FAIRCOM_BATCH_SIZE))

    print(
        f"\nSweeping FairCom worker counts: {worker_counts} "
        f"(batch size {batch_size:,})\n"
    )

    results = []
    for workers in worker_counts:
        print(f"Workers {workers:>3} ...", end="", flush=True)
        res = load_faircom.load(
            batch_size=batch_size, workers=workers, show_progress=False
        )
        rps = res["rows"] / res["seconds"] if res["seconds"] else 0
        results.append((workers, res["seconds"], rps))
        print(f" {res['seconds']:7.2f}s   {rps:>12,.0f} rows/sec")

    best = max(results, key=lambda r: r[2])
    baseline = next((r for r in results if r[0] == 1), results[0])
    print("\n" + "=" * 60)
    print("  FAIRCOM CONCURRENCY SWEEP")
    print("=" * 60)
    print(f"  {'workers':>8}  {'seconds':>10}  {'rows/sec':>14}  {'speedup':>8}")
    print("  " + "-" * 48)
    for workers, secs, rps in results:
        speedup = rps / baseline[2] if baseline[2] else 0
        marker = "  <- best" if (workers, secs, rps) == best else ""
        print(f"  {workers:>8}  {secs:>10.2f}  {rps:>14,.0f}  {speedup:>7.2f}x{marker}")
    print("=" * 60)
    print(
        f"\n  Fastest: {best[0]} workers at {best[2]:,.0f} rows/sec "
        f"({best[1]:.2f}s), {best[2] / baseline[2]:.1f}x the single-worker rate.\n"
    )


if __name__ == "__main__":
    main()
