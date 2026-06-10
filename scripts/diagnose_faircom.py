"""FairCom REST load diagnostics for UAT.

This is an internal diagnostic tool, not a sales demo. Its job is to show the
engineering team *where* the JSON Action REST API loading path spends its time,
so the loading process can be improved.

It runs the same insertRecords load as scripts/load_faircom.py but instruments
each phase and every request, then prints:

  1. Phase breakdown      - setup vs CSV read vs insert (wall-clock seconds)
  2. Per-request latency   - min / median / p95 / max / mean for each POST
  3. Client vs network      - time spent building JSON in Python vs the
                              request/response round-trip
  4. Throughput summary     - rows/sec, requests, effective concurrency

Usage:
    python3 scripts/diagnose_faircom.py
    BATCH=5000 WORKERS=4 python3 scripts/diagnose_faircom.py
"""
from __future__ import annotations

import csv
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from config import (
    COLUMNS,
    DATA_FILE,
    FAIRCOM_BATCH_SIZE,
    FAIRCOM_URL,
    FAIRCOM_WORKERS,
    TABLE_NAME,
)
from load_faircom import FIELDS, FairComError, _create_session, _row_to_record


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in 0..100)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100) * (len(sorted_vals) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = rank - low
    return sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * frac


def _fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms"


def main() -> None:
    batch_size = int(os.environ.get("BATCH", FAIRCOM_BATCH_SIZE))
    workers = int(os.environ.get("WORKERS", FAIRCOM_WORKERS))

    # ----- Phase 1: setup (session + drop + create table) -----------------
    setup_start = time.perf_counter()
    session = requests.Session()
    auth_token, database, owner = _create_session(session)
    session.headers.update({"Content-Type": "application/json"})
    base_params = {"databaseName": database, "ownerName": owner, "tableName": TABLE_NAME}
    common = {"authToken": auth_token}

    try:
        session.post(
            FAIRCOM_URL,
            json={
                "api": "db",
                "action": "deleteTables",
                "params": {"databaseName": database, "ownerName": owner,
                           "tableNames": [TABLE_NAME]},
                **common,
            },
            timeout=120,
        )
    except requests.RequestException:
        pass

    resp = session.post(
        FAIRCOM_URL,
        json={"api": "db", "action": "createTable",
              "params": {**base_params, "fields": FIELDS}, **common},
        timeout=120,
    )
    resp.raise_for_status()
    setup_seconds = time.perf_counter() - setup_start

    # ----- Phase 2: read + parse the CSV ----------------------------------
    read_start = time.perf_counter()
    with DATA_FILE.open(newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        records = [_row_to_record(r) for r in reader]
    read_seconds = time.perf_counter() - read_start

    batches = [records[i : i + batch_size] for i in range(0, len(records), batch_size)]

    # ----- Phase 3: insert, instrumenting each request --------------------
    # Per batch we measure:
    #   serialize_s - time for json.dumps in Python (client CPU)
    #   roundtrip_s - time for the POST (network + server processing)
    serialize_times: list[float] = []
    roundtrip_times: list[float] = []
    lock = threading.Lock()
    local = threading.local()

    def _send(batch: list[dict]) -> None:
        s = getattr(local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"Content-Type": "application/json"})
            local.session = s

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
        resp = s.post(FAIRCOM_URL, data=body, timeout=120)
        t2 = time.perf_counter()

        resp.raise_for_status()
        parsed = resp.json()
        if parsed.get("errorCode", 0) not in (0, None):
            raise FairComError(f"{parsed.get('errorCode')}: {parsed.get('errorMessage')}")

        with lock:
            serialize_times.append(t1 - t0)
            roundtrip_times.append(t2 - t1)

    insert_start = time.perf_counter()
    if workers <= 1:
        for b in batches:
            _send(b)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_send, b) for b in batches]
            for fut in as_completed(futures):
                fut.result()
    insert_seconds = time.perf_counter() - insert_start

    session.close()

    # ----- Report ---------------------------------------------------------
    rows = len(records)
    n_req = len(batches)
    total_wall = setup_seconds + read_seconds + insert_seconds
    rps = rows / insert_seconds if insert_seconds else 0

    rt_sorted = sorted(roundtrip_times)
    ser_sum = sum(serialize_times)
    rt_sum = sum(roundtrip_times)
    busy_sum = ser_sum + rt_sum  # total per-request work across all threads
    concurrency = busy_sum / insert_seconds if insert_seconds else 0

    bar = "=" * 70
    print(f"\n{bar}")
    print("  FAIRCOM REST LOAD DIAGNOSTICS (UAT)")
    print(bar)
    print(f"  dataset           {rows:,} rows")
    print(f"  batch size        {batch_size:,} rows/request  ->  {n_req:,} requests")
    print(f"  workers           {workers} concurrent thread(s)")
    print(f"  endpoint          {FAIRCOM_URL}")

    print(f"\n  PHASE BREAKDOWN (wall-clock)")
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

    print(f"\n  PER-REQUEST LATENCY (insertRecords round-trip)")
    print("  " + "-" * 60)
    print(f"  {'min':>10}{'median':>12}{'p95':>12}{'max':>12}{'mean':>12}")
    mean_rt = (rt_sum / n_req) if n_req else 0
    print(
        f"  {_fmt_ms(rt_sorted[0]):>10}"
        f"{_fmt_ms(_percentile(rt_sorted, 50)):>12}"
        f"{_fmt_ms(_percentile(rt_sorted, 95)):>12}"
        f"{_fmt_ms(rt_sorted[-1]):>12}"
        f"{_fmt_ms(mean_rt):>12}"
    )

    print(f"\n  CLIENT vs NETWORK (summed across all requests)")
    print("  " + "-" * 60)
    busy = busy_sum or 1
    print(
        f"  {'JSON build (client CPU)':<28}{ser_sum:>10.3f}s"
        f"{ser_sum / busy * 100:>10.1f}%"
    )
    print(
        f"  {'round-trip (net+server)':<28}{rt_sum:>10.3f}s"
        f"{rt_sum / busy * 100:>10.1f}%"
    )

    print(f"\n  THROUGHPUT")
    print("  " + "-" * 60)
    print(f"  insert wall-clock         {insert_seconds:.2f}s")
    print(f"  rows/sec                  {rps:,.0f}")
    print(f"  effective concurrency     {concurrency:.2f}x  (of {workers} workers)")
    print(bar)

    # Plain-English takeaway to guide engineering.
    print("\n  TAKEAWAY")
    if ser_sum > rt_sum:
        print("  - Client-side JSON serialization dominates: a leaner wire")
        print("    format (e.g. dataFormat 'arrays') or streaming encoder would help.")
    else:
        print("  - Round-trip (network + server insert) dominates: the win is")
        print("    server-side ingest speed and/or higher useful concurrency.")
    if workers > 1 and concurrency < workers * 0.75:
        print(
            f"  - Only ~{concurrency:.1f} of {workers} workers' worth of work overlapped:"
        )
        print("    requests are serializing somewhere (server lock or single queue?).")
    print(bar + "\n")


if __name__ == "__main__":
    main()
