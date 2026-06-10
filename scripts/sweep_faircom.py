"""Find the fastest FairCom batch size for the JSON insertRecords loader.

FairCom loads over the JSON REST API, so each batch is one HTTP request. Tiny
batches mean too many round trips; huge batches mean large JSON payloads. This
script loads the same dataset several times with different batch sizes and
reports the throughput of each so you can pick the sweet spot for the demo.

Usage:
    python3 scripts/sweep_faircom.py                 # default batch sizes
    python3 scripts/sweep_faircom.py 1000 5000 25000 # custom batch sizes
"""
from __future__ import annotations

import sys

import load_faircom

DEFAULT_BATCH_SIZES = [1000, 2500, 5000, 10000, 25000, 50000]


def main() -> None:
    if len(sys.argv) > 1:
        batch_sizes = [int(a) for a in sys.argv[1:]]
    else:
        batch_sizes = DEFAULT_BATCH_SIZES

    print(f"\nSweeping FairCom batch sizes: {batch_sizes}\n")

    results = []
    for size in batch_sizes:
        print(f"Batch size {size:>7,} ...", end="", flush=True)
        res = load_faircom.load(batch_size=size, show_progress=False)
        rps = res["rows"] / res["seconds"] if res["seconds"] else 0
        results.append((size, res["seconds"], rps))
        print(f" {res['seconds']:7.2f}s   {rps:>12,.0f} rows/sec")

    best = max(results, key=lambda r: r[2])
    print("\n" + "=" * 60)
    print("  FAIRCOM BATCH-SIZE SWEEP")
    print("=" * 60)
    print(f"  {'batch size':>12}  {'seconds':>10}  {'rows/sec':>14}")
    print("  " + "-" * 40)
    for size, secs, rps in results:
        marker = "  <- best" if (size, secs, rps) == best else ""
        print(f"  {size:>12,}  {secs:>10.2f}  {rps:>14,.0f}{marker}")
    print("=" * 60)
    print(
        f"\n  Fastest: batch size {best[0]:,} at {best[2]:,.0f} rows/sec "
        f"({best[1]:.2f}s).\n"
        f"  Set FAIRCOM_BATCH_SIZE={best[0]} in .env to use it.\n"
    )


if __name__ == "__main__":
    main()
