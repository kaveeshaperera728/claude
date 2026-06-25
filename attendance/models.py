"""Data-access layer for users, devices and attendance records.

Each function accepts an open sqlite3 connection so callers can compose
operations within a single transaction (see db.get_conn).
"""

from __future__ import annotations

import secrets
import sqlite3
import uuid as uuidlib
from typing import Any

from .db import utcnow
from .errors import ConflictError, NotFoundError, ValidationError

VALID_PUNCH_TYPES = {"check_in", "check_out"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def new_uuid() -> str:
    return str(uuidlib.uuid4())


def new_api_key() -> str:
    return "dev_" + secrets.token_urlsafe(32)


def _require(data: dict, field: str) -> Any:
    value = data.get(field)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise ValidationError(f"'{field}' is required")
    return value


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def create_user(conn: sqlite3.Connection, data: dict) -> dict:
    employee_code = _require(data, "employee_code")
    name = _require(data, "name")
    now = utcnow()
    user_uuid = data.get("uuid") or new_uuid()

    try:
        cur = conn.execute(
            """
            INSERT INTO users (uuid, employee_code, name, email, pin, card_id,
                               active, deleted, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                user_uuid,
                str(employee_code),
                str(name),
                data.get("email"),
                data.get("pin"),
                data.get("card_id"),
                1 if data.get("active", True) else 0,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ConflictError(
            f"User with that employee_code or uuid already exists: {exc}"
        ) from exc

    return get_user(conn, cur.lastrowid)


def get_user(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    user = _row_to_dict(row)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user


def get_user_by_uuid(conn: sqlite3.Connection, user_uuid: str) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE uuid = ?", (user_uuid,)).fetchone()
    return _row_to_dict(row)


def find_user_for_punch(
    conn: sqlite3.Connection, data: dict
) -> dict:
    """Resolve a user from identifiers a device might send (uuid/code/pin/card)."""
    if data.get("user_uuid"):
        row = conn.execute(
            "SELECT * FROM users WHERE uuid = ? AND deleted = 0", (data["user_uuid"],)
        ).fetchone()
    elif data.get("employee_code"):
        row = conn.execute(
            "SELECT * FROM users WHERE employee_code = ? AND deleted = 0",
            (data["employee_code"],),
        ).fetchone()
    elif data.get("card_id"):
        row = conn.execute(
            "SELECT * FROM users WHERE card_id = ? AND deleted = 0", (data["card_id"],)
        ).fetchone()
    elif data.get("pin"):
        row = conn.execute(
            "SELECT * FROM users WHERE pin = ? AND deleted = 0", (data["pin"],)
        ).fetchone()
    else:
        raise ValidationError(
            "Provide one of: user_uuid, employee_code, card_id or pin"
        )

    user = _row_to_dict(row)
    if user is None:
        raise NotFoundError("No active user matches the supplied identifier")
    if not user["active"]:
        raise ValidationError("User is not active")
    return user


def list_users(
    conn: sqlite3.Connection, include_deleted: bool = False
) -> list[dict]:
    sql = "SELECT * FROM users"
    if not include_deleted:
        sql += " WHERE deleted = 0"
    sql += " ORDER BY name COLLATE NOCASE"
    return [dict(r) for r in conn.execute(sql).fetchall()]


def update_user(conn: sqlite3.Connection, user_id: int, data: dict) -> dict:
    user = get_user(conn, user_id)
    fields = ["employee_code", "name", "email", "pin", "card_id", "active"]
    updates = {}
    for f in fields:
        if f in data:
            updates[f] = (1 if data[f] else 0) if f == "active" else data[f]

    if not updates:
        return user

    updates["updated_at"] = utcnow()
    assignments = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [user_id]
    try:
        conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", values)
    except sqlite3.IntegrityError as exc:
        raise ConflictError(f"Update violates a unique constraint: {exc}") from exc
    return get_user(conn, user_id)


def delete_user(conn: sqlite3.Connection, user_id: int) -> dict:
    """Soft-delete so the change can propagate to devices during sync."""
    get_user(conn, user_id)
    conn.execute(
        "UPDATE users SET deleted = 1, active = 0, updated_at = ? WHERE id = ?",
        (utcnow(), user_id),
    )
    return {"deleted": True, "id": user_id}


def users_changed_since(conn: sqlite3.Connection, since: str | None) -> list[dict]:
    """Return users (including deletes) modified strictly after `since`."""
    if since:
        rows = conn.execute(
            "SELECT * FROM users WHERE updated_at > ? ORDER BY updated_at", (since,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY updated_at"
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
def create_device(conn: sqlite3.Connection, data: dict) -> dict:
    name = _require(data, "name")
    now = utcnow()
    device_uuid = data.get("uuid") or new_uuid()
    api_key = data.get("api_key") or new_api_key()
    status = data.get("status", "active")

    try:
        cur = conn.execute(
            """
            INSERT INTO devices (uuid, name, location, api_key, status,
                                 last_sync_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (device_uuid, str(name), data.get("location"), api_key, status, now, now),
        )
    except sqlite3.IntegrityError as exc:
        raise ConflictError(f"Device uuid/api_key already exists: {exc}") from exc

    return get_device(conn, cur.lastrowid)


def get_device(conn: sqlite3.Connection, device_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM devices WHERE id = ?", (device_id,)
    ).fetchone()
    device = _row_to_dict(row)
    if device is None:
        raise NotFoundError(f"Device {device_id} not found")
    return device


def get_device_by_api_key(conn: sqlite3.Connection, api_key: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM devices WHERE api_key = ?", (api_key,)
    ).fetchone()
    return _row_to_dict(row)


def list_devices(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM devices ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def update_device(conn: sqlite3.Connection, device_id: int, data: dict) -> dict:
    get_device(conn, device_id)
    fields = ["name", "location", "status"]
    updates = {f: data[f] for f in fields if f in data}
    if data.get("rotate_api_key"):
        updates["api_key"] = new_api_key()

    if not updates:
        return get_device(conn, device_id)

    updates["updated_at"] = utcnow()
    assignments = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [device_id]
    conn.execute(f"UPDATE devices SET {assignments} WHERE id = ?", values)
    return get_device(conn, device_id)


def delete_device(conn: sqlite3.Connection, device_id: int) -> dict:
    get_device(conn, device_id)
    conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    return {"deleted": True, "id": device_id}


def touch_device_sync(conn: sqlite3.Connection, device_id: int) -> None:
    conn.execute(
        "UPDATE devices SET last_sync_at = ? WHERE id = ?", (utcnow(), device_id)
    )


# --------------------------------------------------------------------------- #
# Attendance records
# --------------------------------------------------------------------------- #
def record_punch(
    conn: sqlite3.Connection,
    user_id: int,
    punch_type: str,
    punch_time: str | None = None,
    device_id: int | None = None,
    source: str = "device",
    record_uuid: str | None = None,
) -> tuple[dict, bool]:
    """Insert a punch. Returns (record, created).

    `created` is False when an identical uuid already exists (idempotent push).
    """
    if punch_type not in VALID_PUNCH_TYPES:
        raise ValidationError(
            f"punch_type must be one of {sorted(VALID_PUNCH_TYPES)}"
        )

    record_uuid = record_uuid or new_uuid()
    existing = conn.execute(
        "SELECT * FROM attendance_records WHERE uuid = ?", (record_uuid,)
    ).fetchone()
    if existing is not None:
        return dict(existing), False

    now = utcnow()
    cur = conn.execute(
        """
        INSERT INTO attendance_records (uuid, user_id, device_id, punch_type,
                                        punch_time, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (record_uuid, user_id, device_id, punch_type, punch_time or now, source, now),
    )
    row = conn.execute(
        "SELECT * FROM attendance_records WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row), True


def list_records(
    conn: sqlite3.Connection,
    user_id: int | None = None,
    device_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> list[dict]:
    clauses = []
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if device_id is not None:
        clauses.append("device_id = ?")
        params.append(device_id)
    if date_from:
        clauses.append("punch_time >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("punch_time <= ?")
        params.append(date_to)

    sql = "SELECT * FROM attendance_records"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY punch_time DESC LIMIT ?"
    params.append(int(limit))
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
