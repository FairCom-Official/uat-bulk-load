"""Load the sample dataset into FairCom Edge via the JSON Action REST API.

FairCom has no LOAD DATA INFILE statement, so we read the shared CSV in Python
and post it to the server using the JSON DB "insertRecords" action in batches.

Flow (all POSTs go to a single /api endpoint):
  1. createSession (api=admin) -> authToken
  2. deleteTables  (api=db)    -> drop any prior run (ignored if missing)
  3. createTable   (api=db)    -> define the schema
  4. insertRecords (api=db)    -> batched bulk insert (this is what we time)
"""
from __future__ import annotations

import csv
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from config import (
    COLUMNS,
    DATA_FILE,
    FAIRCOM_BATCH_SIZE,
    FAIRCOM_PASSWORD,
    FAIRCOM_URL,
    FAIRCOM_USER,
    FAIRCOM_WORKERS,
    TABLE_NAME,
)
from progress import make_bar

# Field definitions mirror sql/mariadb_schema.sql so both engines hold the same
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
    """Load the dataset via insertRecords.

    workers=1 posts batches sequentially. workers>1 posts batches concurrently
    using a thread pool, where each thread keeps its own requests.Session (they
    are not thread-safe) but shares the single authToken.
    """
    batch_size = batch_size or FAIRCOM_BATCH_SIZE
    workers = workers or FAIRCOM_WORKERS
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

    # Read the entire CSV (skip header), then time only the insert phase.
    with DATA_FILE.open(newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        records = [_row_to_record(r) for r in reader]

    start = time.perf_counter()
    bar = make_bar("FairCom load", len(records)) if show_progress else None

    def _insert_batch(post_session: requests.Session, batch: list[dict]) -> int:
        _post(
            post_session,
            {
                "api": "db",
                "action": "insertRecords",
                "params": {
                    **base_params,
                    "dataFormat": "objects",
                    "fieldNames": COLUMNS,
                    "sourceData": batch,
                },
                **common,
            },
        )
        return len(batch)

    batches = [
        records[i : i + batch_size]
        for i in range(0, len(records), batch_size)
    ]

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
    elapsed = time.perf_counter() - start

    return {
        "engine": "FairCom Edge (JSON insertRecords)",
        "rows": len(records),
        "seconds": elapsed,
        "batch_size": batch_size,
        "workers": workers,
    }


if __name__ == "__main__":
    result = load()
    rps = result["rows"] / result["seconds"] if result["seconds"] else 0
    print(
        f"{result['engine']}: loaded {result['rows']:,} rows "
        f"in {result['seconds']:.2f}s ({rps:,.0f} rows/sec)"
    )
