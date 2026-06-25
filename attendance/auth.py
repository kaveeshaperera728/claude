"""Authentication helpers.

Two authentication schemes are supported:

* Admin / management endpoints use a bearer token (``Authorization: Bearer ...``)
  configured via the ``ADMIN_TOKEN`` environment variable.
* Device / sync endpoints authenticate with a per-device API key supplied in the
  ``X-API-Key`` header.
"""

from __future__ import annotations

import hmac
import os
import sqlite3

from . import models
from .errors import AuthError

DEFAULT_ADMIN_TOKEN = "admin-secret"


def admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)


def require_admin(headers) -> None:
    """Validate the admin bearer token. Raises AuthError on failure."""
    raw = headers.get("Authorization", "")
    expected = admin_token()
    if raw.startswith("Bearer "):
        provided = raw[len("Bearer ") :].strip()
    else:
        provided = headers.get("X-Admin-Token", "").strip()

    if not provided or not hmac.compare_digest(provided, expected):
        raise AuthError("Invalid or missing admin credentials")


def require_device(conn: sqlite3.Connection, headers) -> dict:
    """Resolve and return the device for the supplied API key.

    Raises AuthError if the key is missing, unknown or the device is inactive.
    """
    api_key = headers.get("X-API-Key", "").strip()
    if not api_key:
        raise AuthError("Missing X-API-Key header")

    device = models.get_device_by_api_key(conn, api_key)
    if device is None:
        raise AuthError("Unknown device API key")
    if device["status"] != "active":
        raise AuthError("Device is not active")
    return device
