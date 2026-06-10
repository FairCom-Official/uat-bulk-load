"""Load the sample dataset into a SQL database using LOAD DATA LOCAL INFILE.

The target engine is MariaDB by default, but the same path works for any
MySQL-compatible server (set SQL_ENGINE_LABEL / SQL_* connection settings in
.env). LOAD DATA LOCAL INFILE streams the CSV from the *client* (this Python
process) to the server over the connection, rather than the server reading a
file off its own disk. That makes it a fairer comparison to the FairCom loader,
which also sends the data over the network. The server is started with
--local-infile=1 so it accepts client-streamed files.
"""
from __future__ import annotations

import threading
import time

import pymysql

from config import (
    DATA_FILE,
    ROOT,
    SQL_DATABASE,
    SQL_ENGINE_LABEL,
    SQL_HOST,
    SQL_PASSWORD,
    SQL_PORT,
    SQL_USER,
    TABLE_NAME,
)
from progress import make_bar


def _connect() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=SQL_HOST,
        port=SQL_PORT,
        user=SQL_USER,
        password=SQL_PASSWORD,
        database=SQL_DATABASE,
        local_infile=True,
        autocommit=True,
    )


def _create_table(conn: pymysql.connections.Connection) -> None:
    schema = (ROOT / "sql" / "schema.sql").read_text()
    with conn.cursor() as cur:
        for statement in filter(None, (s.strip() for s in schema.split(";"))):
            cur.execute(statement)


def _expected_rows() -> int:
    """Row count of the CSV (excluding the header) for the progress total."""
    with (ROOT / "data" / "sample.csv").open() as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def load() -> dict:
    """Create the table, run LOAD DATA LOCAL INFILE, and return timing info.

    LOAD DATA LOCAL INFILE is a single blocking statement, so we run it on a
    background thread and poll COUNT(*) to drive a progress bar that matches the
    FairCom loader's bar.
    """
    conn = _connect()
    try:
        _create_table(conn)

        load_sql = (
            f"LOAD DATA LOCAL INFILE '{DATA_FILE}' "
            f"INTO TABLE {TABLE_NAME} "
            "FIELDS TERMINATED BY ',' ENCLOSED BY '\"' "
            "LINES TERMINATED BY '\\n' "
            "IGNORE 1 LINES "
            "(id, device_id, metric, reading, recorded_at, status)"
        )

        total = _expected_rows()
        error: list[BaseException] = []

        def _run_load() -> None:
            try:
                with conn.cursor() as cur:
                    cur.execute(load_sql)
            except BaseException as exc:  # surface on the main thread
                error.append(exc)

        start = time.perf_counter()
        worker = threading.Thread(target=_run_load)
        worker.start()

        bar = make_bar(f"{SQL_ENGINE_LABEL} load", total)
        poller = _connect()
        try:
            while worker.is_alive():
                if bar is not None:
                    with poller.cursor() as cur:
                        cur.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
                        loaded = cur.fetchone()[0]
                    bar.n = min(loaded, total)
                    bar.refresh()
                time.sleep(0.1)
            worker.join()
        finally:
            poller.close()
            if bar is not None:
                bar.n = total
                bar.refresh()
                bar.close()

        if error:
            raise error[0]
        elapsed = time.perf_counter() - start

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
            rows = cur.fetchone()[0]
    finally:
        conn.close()

    return {
        "engine": f"{SQL_ENGINE_LABEL} (LOAD DATA LOCAL INFILE)",
        "rows": rows,
        "seconds": elapsed,
    }


if __name__ == "__main__":
    result = load()
    rps = result["rows"] / result["seconds"] if result["seconds"] else 0
    print(
        f"{result['engine']}: loaded {result['rows']:,} rows "
        f"in {result['seconds']:.2f}s ({rps:,.0f} rows/sec)"
    )
