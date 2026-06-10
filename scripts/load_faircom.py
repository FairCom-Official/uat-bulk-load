"""Load the sample dataset into FairCom via the JSON Action REST API.

The same REST path works for any FairCom server (DB, Edge, Cloud), since Edge is
built on FairCom DB. FairCom has no LOAD DATA INFILE statement, so we read the
shared CSV in Python and post it to the server using the JSON DB "insertRecords"
action in batches.

Flow (all POSTs go to a single /api endpoint):
  1. createSession (api=admin) -> authToken
  2. deleteTables  (api=db)    -> drop any prior run (ignored if missing)
  3. createTable   (api=db)    -> define the schema
  4. insertRecords (api=db)    -> batched bulk insert (this is what we time)
"""
from __future__ import annotations

import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from config import (
    COLUMNS,
    DATA_FILE,
    FAIRCOM_BATCH_SIZE,
    FAIRCOM_LABEL,
    FAIRCOM_PASSWORD,
    FAIRCOM_URL,
    FAIRCOM_USER,
    FAIRCOM_WORKERS,
    TABLE_NAME,
)
from progress import make_bar

# Field definitions mirror sql/schema.sql so both engines hold the same
# data. "float" is double precision and needs no length/scale.
FIELDS = [
    {"name": "id", "type": "bigint", "primaryKey": 1, "nullable": False},
    {"name": "device_id", "type": "varchar", "length": 32},
    {"name": "metric", "type": "varchar", "length": 32},
    {"name": "reading", "type": "float"},
    {"name": "recorded_at", "type": "varchar", "length": 32},
    {"name": "status", "type": "varchar", "length": 16},
]


class FairComError(RuntimeError):
    """Raised when the server returns a non-zero errorCode."""


def _post(session: requests.Session, payload: dict[str, Any]) -> dict:
    resp = session.post(FAIRCOM_URL, json=payload, timeout=120)
    resp.raise_for_status()
    body = resp.json()
    if body.get("errorCode", 0) not in (0, None):
        raise FairComError(f"{body.get('errorCode')}: {body.get('errorMessage')}")
    return body


def _create_session(session: requests.Session) -> tuple[str, str, str]:
    body = _post(
        session,
        {
            "api": "admin",
            "action": "createSession",
            "params": {"username": FAIRCOM_USER, "password": FAIRCOM_PASSWORD},
        },
    )
    result = body["result"]
    return (
        result["authToken"],
        result.get("defaultDatabaseName"),
        result.get("defaultOwnerName"),
    )


def _row_to_record(row: list[str]) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "device_id": row[1],
        "metric": row[2],
        "reading": float(row[3]),
        "recorded_at": row[4],
        "status": row[5],
    }


def load(
    batch_size: int | None = None,
    show_progress: bool = True,
    workers: int | None = None,
) -> dict:
    """Load the dataset via insertRecords, timing the load and each request.

    workers=1 posts batches sequentially. workers>1 posts batches concurrently
    using a thread pool, where each thread keeps its own requests.Session (they
    are not thread-safe) but shares the single authToken.

    The returned dict carries everything the diagnostics report needs, so the
    load only ever runs once (see print_diagnostics).
    """
    batch_size = batch_size or FAIRCOM_BATCH_SIZE
    workers = workers or FAIRCOM_WORKERS

    # ----- setup: session + drop + create table --------------------------
    setup_start = time.perf_counter()
    session = requests.Session()
    auth_token, database, owner = _create_session(session)
    session.headers.update({"Content-Type": "application/json"})

    base_params = {"databaseName": database, "ownerName": owner, "tableName": TABLE_NAME}
    common = {"authToken": auth_token}

    # Drop any table left over from a previous run (ignore "does not exist").
    try:
        _post(
            session,
            {
                "api": "db",
                "action": "deleteTables",
                "params": {"databaseName": database, "ownerName": owner,
                           "tableNames": [TABLE_NAME]},
                **common,
            },
        )
    except FairComError:
        pass

    _post(
        session,
        {
            "api": "db",
            "action": "createTable",
            "params": {**base_params, "fields": FIELDS},
            **common,
        },
    )
    setup_seconds = time.perf_counter() - setup_start

    # ----- read + parse the CSV (skip header) -----------------------------
    read_start = time.perf_counter()
    with DATA_FILE.open(newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        records = [_row_to_record(r) for r in reader]
    read_seconds = time.perf_counter() - read_start

    batches = [
        records[i : i + batch_size]
        for i in range(0, len(records), batch_size)
    ]

    # Per-request timings: JSON build (client CPU) vs round-trip (net+server).
    serialize_times: list[float] = []
    roundtrip_times: list[float] = []
    lock = threading.Lock()

    def _insert_batch(post_session: requests.Session, batch: list[dict]) -> int:
        payload = {
            "api": "db",
            "action": "insertRecords",
            "params": {
                **base_params,
                "dataFormat": "objects",
                "fieldNames": COLUMNS,
                "sourceData": batch,
            },
            **common,
        }
        t0 = time.perf_counter()
        body = json.dumps(payload)
        t1 = time.perf_counter()
        resp = post_session.post(FAIRCOM_URL, data=body, timeout=120)
        t2 = time.perf_counter()
        resp.raise_for_status()
        parsed = resp.json()
        if parsed.get("errorCode", 0) not in (0, None):
            raise FairComError(
                f"{parsed.get('errorCode')}: {parsed.get('errorMessage')}"
            )
        with lock:
            serialize_times.append(t1 - t0)
            roundtrip_times.append(t2 - t1)
        return len(batch)

    # ----- insert (this is what the benchmark times) ----------------------
    insert_start = time.perf_counter()
    bar = make_bar(f"{FAIRCOM_LABEL} load", len(records)) if show_progress else None

    if workers <= 1:
        for batch in batches:
            _insert_batch(session, batch)
            if bar is not None:
                bar.update(len(batch))
    else:
        # Each worker thread reuses one Session via thread-local storage.
        local = threading.local()

        def _worker(batch: list[dict]) -> int:
            s = getattr(local, "session", None)
            if s is None:
                s = requests.Session()
                s.headers.update({"Content-Type": "application/json"})
                local.session = s
            return _insert_batch(s, batch)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, b) for b in batches]
            for fut in as_completed(futures):
                n = fut.result()
                if bar is not None:
                    bar.update(n)

    if bar is not None:
        bar.close()
    insert_seconds = time.perf_counter() - insert_start
    session.close()

    return {
        "engine": f"{FAIRCOM_LABEL} (JSON insertRecords)",
        "rows": len(records),
        "seconds": insert_seconds,
        "batch_size": batch_size,
        "workers": workers,
        "setup_seconds": setup_seconds,
        "read_seconds": read_seconds,
        "serialize_times": serialize_times,
        "roundtrip_times": roundtrip_times,
    }


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in 0..100)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100) * (len(sorted_vals) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    return sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * (rank - low)


def print_diagnostics(result: dict) -> None:
    """Print where the FairCom REST load spent its time.

    Reads the metrics captured during load() so the load runs only once.
    """
    rows = result["rows"]
    batch_size = result["batch_size"]
    workers = result["workers"]
    setup_seconds = result["setup_seconds"]
    read_seconds = result["read_seconds"]
    insert_seconds = result["seconds"]
    serialize_times = result["serialize_times"]
    roundtrip_times = result["roundtrip_times"]

    n_req = len(roundtrip_times)
    total_wall = setup_seconds + read_seconds + insert_seconds
    rps = rows / insert_seconds if insert_seconds else 0

    rt_sorted = sorted(roundtrip_times)
    ser_sum = sum(serialize_times)
    rt_sum = sum(roundtrip_times)
    busy_sum = ser_sum + rt_sum
    concurrency = busy_sum / insert_seconds if insert_seconds else 0

    def ms(seconds: float) -> str:
        return f"{seconds * 1000:.1f} ms"

    bar = "=" * 70
    print(f"\n{bar}")
    print("  FAIRCOM REST LOAD DIAGNOSTICS (UAT)")
    print(bar)
    print(f"  dataset           {rows:,} rows")
    print(f"  batch size        {batch_size:,} rows/request  ->  {n_req:,} requests")
    print(f"  workers           {workers} concurrent thread(s)")
    print(f"  endpoint          {FAIRCOM_URL}")

    print("\n  PHASE BREAKDOWN (wall-clock)")
    print("  " + "-" * 60)
    print(f"  {'phase':<22}{'seconds':>12}{'% of total':>14}")
    for label, secs in (
        ("1. setup (session+DDL)", setup_seconds),
        ("2. read CSV", read_seconds),
        ("3. insert (REST)", insert_seconds),
    ):
        pct = (secs / total_wall * 100) if total_wall else 0
        print(f"  {label:<22}{secs:>12.3f}{pct:>13.1f}%")
    print("  " + "-" * 60)
    print(f"  {'total':<22}{total_wall:>12.3f}{100.0:>13.1f}%")

    if rt_sorted:
        print("\n  PER-REQUEST LATENCY (insertRecords round-trip)")
        print("  " + "-" * 60)
        print(f"  {'min':>10}{'median':>12}{'p95':>12}{'max':>12}{'mean':>12}")
        mean_rt = rt_sum / n_req if n_req else 0
        print(
            f"  {ms(rt_sorted[0]):>10}"
            f"{ms(_percentile(rt_sorted, 50)):>12}"
            f"{ms(_percentile(rt_sorted, 95)):>12}"
            f"{ms(rt_sorted[-1]):>12}"
            f"{ms(mean_rt):>12}"
        )

    print("\n  CLIENT vs NETWORK (summed across all requests)")
    print("  " + "-" * 60)
    busy = busy_sum or 1
    print(f"  {'JSON build (client CPU)':<28}{ser_sum:>10.3f}s{ser_sum / busy * 100:>10.1f}%")
    print(f"  {'round-trip (net+server)':<28}{rt_sum:>10.3f}s{rt_sum / busy * 100:>10.1f}%")

    print("\n  THROUGHPUT")
    print("  " + "-" * 60)
    print(f"  insert wall-clock         {insert_seconds:.2f}s")
    print(f"  rows/sec                  {rps:,.0f}")
    print(f"  effective concurrency     {concurrency:.2f}x  (of {workers} workers)")
    print(bar)

    print("\n  TAKEAWAY")
    if ser_sum > rt_sum:
        print("  - Most of the time is spent on the client building the JSON to send.")
        print("    A leaner request format would speed this up more than the server.")
    else:
        print("  - Most of the time is spent waiting on each request to come back")
        print("    (network plus the server writing the rows), not on the client.")
    if workers > 1 and concurrency < workers * 0.75:
        print(f"  - Only about {concurrency:.1f} of {workers} requests were truly running at once,")
        print("    so adding more workers may not help until that bottleneck is cleared.")
    print(bar + "\n")


if __name__ == "__main__":
    result = load()
    rps = result["rows"] / result["seconds"] if result["seconds"] else 0
    print(
        f"{result['engine']}: loaded {result['rows']:,} rows "
        f"in {result['seconds']:.2f}s ({rps:,.0f} rows/sec)"
    )
    print_diagnostics(result)
