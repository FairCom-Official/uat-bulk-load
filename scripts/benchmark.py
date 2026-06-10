"""Run both loaders and print a plain-English comparison.

Generates the dataset if it is missing, loads the SQL engine and FairCom from
the exact same CSV, then prints a side-by-side summary.
"""
from __future__ import annotations

import load_faircom
import load_sql
from config import DATA_FILE, ROW_COUNT
from generate_data import generate


def _summary_line(result: dict) -> str:
    rps = result["rows"] / result["seconds"] if result["seconds"] else 0
    return (
        f"  {result['engine']:<38} "
        f"{result['rows']:>10,} rows  "
        f"{result['seconds']:>8.2f}s  "
        f"{rps:>12,.0f} rows/sec"
    )


def _existing_row_count() -> int:
    """Number of data rows (excluding the header) in the current CSV."""
    with DATA_FILE.open() as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def main() -> None:
    # ROW_COUNT (from .env) is the single source of truth. Regenerate whenever
    # the dataset is missing or its row count no longer matches the setting.
    if not DATA_FILE.exists():
        print(f"Sample data not found, generating {ROW_COUNT:,} rows...")
        generate(ROW_COUNT)
    elif _existing_row_count() != ROW_COUNT:
        print(
            f"Dataset has {_existing_row_count():,} rows but ROW_COUNT is "
            f"{ROW_COUNT:,}; regenerating..."
        )
        generate(ROW_COUNT)
    else:
        print(f"Using existing dataset: {DATA_FILE} ({ROW_COUNT:,} rows)")


    print("\nLoading data (identical dataset into both engines)...\n")
    sql = load_sql.load()
    faircom = load_faircom.load()

    print("\n" + "=" * 78)
    print("  BULK LOAD BENCHMARK RESULTS")
    print("=" * 78)
    print(_summary_line(sql))
    print(_summary_line(faircom))
    print("=" * 78)

    if sql["seconds"] and faircom["seconds"]:
        faster, slower = sorted((sql, faircom), key=lambda r: r["seconds"])
        ratio = slower["seconds"] / faster["seconds"]
        print(
            f"\n  {faster['engine'].split('(')[0].strip()} finished "
            f"{ratio:.1f}x faster on this run.\n"
        )

    # The FairCom load was instrumented as it ran, so show where its time went
    # without loading the data a second time.
    load_faircom.print_diagnostics(faircom)


if __name__ == "__main__":
    main()
