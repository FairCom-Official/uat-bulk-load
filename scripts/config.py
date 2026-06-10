"""Shared configuration loaded from environment / .env file."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv is optional at runtime
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_FILE = DATA_DIR / "sample.csv"

# Column order is fixed and shared by both databases.
COLUMNS = ["id", "device_id", "metric", "reading", "recorded_at", "status"]

TABLE_NAME = os.getenv("TABLE_NAME", "sensor_readings")
ROW_COUNT = int(os.getenv("ROW_COUNT", "100000"))

# FairCom (JSON Action REST API). The same REST path works for any FairCom
# server (DB, Edge, Cloud); FAIRCOM_LABEL is the name shown in benchmark output.
FAIRCOM_LABEL = os.getenv("FAIRCOM_LABEL", "FairCom")
FAIRCOM_URL = os.getenv("FAIRCOM_URL", "http://localhost:8080/api")
FAIRCOM_USER = os.getenv("FAIRCOM_USER", "ADMIN")
FAIRCOM_PASSWORD = os.getenv("FAIRCOM_PASSWORD", "ADMIN")
FAIRCOM_BATCH_SIZE = int(os.getenv("FAIRCOM_BATCH_SIZE", "5000"))
# Number of concurrent threads posting insertRecords batches in parallel.
FAIRCOM_WORKERS = int(os.getenv("FAIRCOM_WORKERS", "4"))

# SQL engine (currently MariaDB; MySQL / PostgreSQL / etc. can be added later).
# SQL_ENGINE_LABEL is the human-readable name shown in benchmark output.
SQL_ENGINE = os.getenv("SQL_ENGINE", "mariadb")
SQL_ENGINE_LABEL = os.getenv("SQL_ENGINE_LABEL", "MariaDB")

# Connection settings. New generic SQL_* names take precedence; the legacy
# MARIADB_* names are still honored so existing .env files keep working.
SQL_HOST = os.getenv("SQL_HOST", os.getenv("MARIADB_HOST", "127.0.0.1"))
SQL_PORT = int(os.getenv("SQL_PORT", os.getenv("MARIADB_PORT", "3306")))
SQL_USER = os.getenv("SQL_USER", os.getenv("MARIADB_USER", "root"))
SQL_PASSWORD = os.getenv("SQL_PASSWORD", os.getenv("MARIADB_ROOT_PASSWORD", "benchmark"))
SQL_DATABASE = os.getenv("SQL_DATABASE", os.getenv("MARIADB_DATABASE", "benchmark"))

# Path to the CSV as seen *inside* the database container (mounted volume).
SQL_INFILE_PATH = "/data/sample.csv"
