"""Synchronisation logic for offline-capable devices.

A device periodically calls the sync endpoint to:

1. **Push** punches it recorded while offline. Pushes are idempotent: each
   punch carries a client-generated ``uuid`` so retries never create
   duplicates.
2. **Pull** the set of users that changed (created/updated/deleted) since the
   device last synced, so the device's local roster stays current.

The server is the source of truth. Conflicts are avoided by giving every punch
a stable uuid and by tracking user changes with monotonically increasing
``updated_at`` timestamps.
"""

from __future__ import annotations

import sqlite3

from . import models
from .db import utcnow
from .errors import NotFoundError, ValidationError


def push_records(
    conn: sqlite3.Connection, device_id: int, records: list[dict]
) -> dict:
    """Apply a batch of punches from a device. Returns a per-record summary."""
    if not isinstance(records, list):
        raise ValidationError("'records' must be a list")

    accepted: list[dict] = []
    duplicates: list[str] = []
    rejected: list[dict] = []

    for raw in records:
        if not isinstance(raw, dict):
            rejected.append({"record": raw, "reason": "not an object"})
            continue
        try:
            user = _resolve_user(conn, raw)
            record, created = models.record_punch(
                conn,
                user_id=user["id"],
                punch_type=raw.get("punch_type"),
                punch_time=raw.get("punch_time"),
                device_id=device_id,
                source="device",
                record_uuid=raw.get("uuid"),
            )
            if created:
                accepted.append(record)
            else:
                duplicates.append(record["uuid"])
        except (ValidationError, NotFoundError) as exc:
            rejected.append({"record": raw, "reason": exc.message})

    return {
        "accepted": len(accepted),
        "duplicates": len(duplicates),
        "rejected": rejected,
        "accepted_records": accepted,
        "duplicate_uuids": duplicates,
    }


def _resolve_user(conn: sqlite3.Connection, raw: dict) -> dict:
    """Find the user a pushed punch belongs to."""
    if raw.get("user_id"):
        return models.get_user(conn, int(raw["user_id"]))
    return models.find_user_for_punch(conn, raw)


def pull_users(conn: sqlite3.Connection, since: str | None) -> dict:
    """Return users changed since `since` plus the authoritative server time."""
    changed = models.users_changed_since(conn, since)
    return {
        "server_time": utcnow(),
        "since": since,
        "users": changed,
        "count": len(changed),
    }


def sync(conn: sqlite3.Connection, device: dict, payload: dict) -> dict:
    """Combined push + pull. Updates the device's last_sync_at timestamp."""
    payload = payload or {}
    records = payload.get("records", [])
    since = payload.get("since") or device.get("last_sync_at")

    push_result = push_records(conn, device["id"], records)
    pull_result = pull_users(conn, since)

    models.touch_device_sync(conn, device["id"])
    conn.execute(
        """
        INSERT INTO sync_log (device_id, pushed_count, pulled_count, synced_at)
        VALUES (?, ?, ?, ?)
        """,
        (device["id"], push_result["accepted"], pull_result["count"], utcnow()),
    )

    return {
        "device_id": device["id"],
        "push": push_result,
        "pull": pull_result,
        "synced_at": utcnow(),
    }
