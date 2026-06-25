"""Database layer: connection management, schema and small query helpers.

Uses SQLite via the standard library. A fresh connection is created per
request/operation so the layer is safe to use from the threaded HTTP server.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

# Default database location can be overridden with the ATTENDANCE_DB env var.
DEFAULT_DB_PATH = os.environ.get(
    "ATTENDANCE_DB", os.path.join(os.getcwd(), "attendance.db")
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid          TEXT    NOT NULL UNIQUE,
    employee_code TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    email         TEXT,
    pin           TEXT,
    card_id       TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    deleted       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_updated_at ON users(updated_at);
CREATE INDEX IF NOT EXISTS idx_users_card_id    ON users(card_id);

CREATE TABLE IF NOT EXISTS devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    location     TEXT,
    api_key      TEXT    NOT NULL UNIQUE,
    status       TEXT    NOT NULL DEFAULT 'active',
    last_sync_at TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_devices_api_key ON devices(api_key);

CREATE TABLE IF NOT EXISTS attendance_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid        TEXT    NOT NULL UNIQUE,
    user_id     INTEGER NOT NULL,
    device_id   INTEGER,
    punch_type  TEXT    NOT NULL,
    punch_time  TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'device',
    created_at  TEXT    NOT NULL,
    FOREIGN KEY (user_id)   REFERENCES users(id),
    FOREIGN KEY (device_id) REFERENCES devices(id)
);

CREATE INDEX IF NOT EXISTS idx_records_user_id    ON attendance_records(user_id);
CREATE INDEX IF NOT EXISTS idx_records_device_id  ON attendance_records(device_id);
CREATE INDEX IF NOT EXISTS idx_records_punch_time ON attendance_records(punch_time);

CREATE TABLE IF NOT EXISTS sync_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER NOT NULL,
    pushed_count  INTEGER NOT NULL DEFAULT 0,
    pulled_count  INTEGER NOT NULL DEFAULT 0,
    synced_at     TEXT    NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(id)
);
"""


def utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Create a new SQLite connection with sensible defaults."""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: str | None = None) -> None:
    """Create all tables and indexes if they do not already exist."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager that yields a connection and commits/rolls back."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_db(db_path: str | None = None) -> None:
    """Drop and recreate every table. Intended for tests and seeding."""
    conn = connect(db_path)
    try:
        for table in ("sync_log", "attendance_records", "devices", "users"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
