"""Generate a deterministic sample dataset shared by both databases.

Writes data/sample.csv with a header row. The same file is consumed by:
  * MariaDB  -> server-side LOAD DATA INFILE
  * FairCom  -> Python reads it and posts via the JSON insertRecords action
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta

from config import COLUMNS, DATA_DIR, DATA_FILE, ROW_COUNT

DEVICES = [f"device-{i:04d}" for i in range(250)]
METRICS = ["temperature", "humidity", "pressure", "vibration", "voltage"]
STATUSES = ["ok", "warn", "alarm"]


def generate(row_count: int, seed: int = 42) -> None:
    rng = random.Random(seed)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    start = datetime(2025, 1, 1)

    with DATA_FILE.open("w", newline="") as fh:
        # Force Unix "\n" line endings. The csv module defaults to "\r\n", which
        # would leave a stray "\r" on the last column (status) when MariaDB's
        # LOAD DATA INFILE splits lines on "\n".
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writerow(COLUMNS)
        for i in range(1, row_count + 1):
            recorded_at = (start + timedelta(seconds=i)).isoformat()
            writer.writerow(
                [
                    i,
                    rng.choice(DEVICES),
                    rng.choice(METRICS),
                    round(rng.uniform(-20.0, 120.0), 4),
                    recorded_at,
                    rng.choices(STATUSES, weights=[90, 8, 2])[0],
                ]
            )

    print(f"Wrote {row_count:,} rows to {DATA_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate sample benchmark data")
    parser.add_argument("--rows", type=int, default=ROW_COUNT)
    args = parser.parse_args()
    generate(args.rows)
