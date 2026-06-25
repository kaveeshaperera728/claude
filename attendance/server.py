"""HTTP layer: a tiny regex router on top of the standard library.

No third-party web framework is used. Routes are registered with a method, a
path pattern (``{name}`` captures a path segment) and a handler. Handlers
receive a :class:`Request` and return ``(status, body)``.
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from . import auth, models, staticfiles, sync
from .db import get_conn, init_db
from .errors import AppError, NotFoundError, ValidationError

Handler = Callable[["Request"], tuple]


class Request:
    """Lightweight wrapper around the parsed HTTP request."""

    def __init__(self, method, path, headers, params, query, body):
        self.method = method
        self.path = path
        self.headers = headers
        self.params = params          # path parameters, e.g. {"id": "3"}
        self.query = query            # query string -> {key: value}
        self.body = body              # parsed JSON body (dict) or {}

    def int_param(self, name: str) -> int:
        try:
            return int(self.params[name])
        except (KeyError, ValueError):
            raise ValidationError(f"Invalid path parameter '{name}'")


class Router:
    def __init__(self):
        self._routes: list[tuple[str, re.Pattern, Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
        self._routes.append((method.upper(), re.compile(f"^{regex}$"), handler))

    def match(self, method: str, path: str):
        path_exists = False
        for m, regex, handler in self._routes:
            match = regex.match(path)
            if match:
                path_exists = True
                if m == method.upper():
                    return handler, match.groupdict()
        if path_exists:
            raise AppError("Method not allowed", status=405)
        raise NotFoundError(f"No route for {method} {path}")


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def health(_req: Request):
    return 200, {"status": "ok"}


# ---- Users (admin) -------------------------------------------------------- #
def create_user(req: Request):
    auth.require_admin(req.headers)
    with get_conn() as conn:
        return 201, models.create_user(conn, req.body)


def list_users(req: Request):
    auth.require_admin(req.headers)
    include_deleted = req.query.get("include_deleted") in ("1", "true", "yes")
    with get_conn() as conn:
        return 200, {"users": models.list_users(conn, include_deleted)}


def get_user(req: Request):
    auth.require_admin(req.headers)
    with get_conn() as conn:
        return 200, models.get_user(conn, req.int_param("id"))


def update_user(req: Request):
    auth.require_admin(req.headers)
    with get_conn() as conn:
        return 200, models.update_user(conn, req.int_param("id"), req.body)


def delete_user(req: Request):
    auth.require_admin(req.headers)
    with get_conn() as conn:
        return 200, models.delete_user(conn, req.int_param("id"))


# ---- Devices (admin) ------------------------------------------------------ #
def create_device(req: Request):
    auth.require_admin(req.headers)
    with get_conn() as conn:
        return 201, models.create_device(conn, req.body)


def list_devices(req: Request):
    auth.require_admin(req.headers)
    with get_conn() as conn:
        return 200, {"devices": models.list_devices(conn)}


def get_device(req: Request):
    auth.require_admin(req.headers)
    with get_conn() as conn:
        return 200, models.get_device(conn, req.int_param("id"))


def update_device(req: Request):
    auth.require_admin(req.headers)
    with get_conn() as conn:
        return 200, models.update_device(conn, req.int_param("id"), req.body)


def delete_device(req: Request):
    auth.require_admin(req.headers)
    with get_conn() as conn:
        return 200, models.delete_device(conn, req.int_param("id"))


# ---- Attendance (admin) --------------------------------------------------- #
def list_attendance(req: Request):
    auth.require_admin(req.headers)
    q = req.query
    with get_conn() as conn:
        records = models.list_records(
            conn,
            user_id=int(q["user_id"]) if q.get("user_id") else None,
            device_id=int(q["device_id"]) if q.get("device_id") else None,
            date_from=q.get("from"),
            date_to=q.get("to"),
            limit=int(q.get("limit", 200)),
        )
    return 200, {"records": records}


def create_attendance(req: Request):
    """Manual punch entry by an administrator."""
    auth.require_admin(req.headers)
    body = req.body
    with get_conn() as conn:
        user = models.get_user(conn, int(body["user_id"])) if body.get(
            "user_id"
        ) else models.find_user_for_punch(conn, body)
        record, created = models.record_punch(
            conn,
            user_id=user["id"],
            punch_type=body.get("punch_type"),
            punch_time=body.get("punch_time"),
            device_id=body.get("device_id"),
            source="manual",
            record_uuid=body.get("uuid"),
        )
    return (201 if created else 200), record


# ---- Device-facing endpoints (API key) ------------------------------------ #
def device_punch(req: Request):
    """A live punch recorded directly by an online device."""
    with get_conn() as conn:
        device = auth.require_device(conn, req.headers)
        user = models.find_user_for_punch(conn, req.body)
        record, created = models.record_punch(
            conn,
            user_id=user["id"],
            punch_type=req.body.get("punch_type"),
            punch_time=req.body.get("punch_time"),
            device_id=device["id"],
            source="device",
            record_uuid=req.body.get("uuid"),
        )
    return (201 if created else 200), {
        "record": record,
        "user": {"id": user["id"], "name": user["name"]},
        "created": created,
    }


def device_sync(req: Request):
    with get_conn() as conn:
        device = auth.require_device(conn, req.headers)
        result = sync.sync(conn, device, req.body)
    return 200, result


def device_pull(req: Request):
    with get_conn() as conn:
        device = auth.require_device(conn, req.headers)
        since = req.query.get("since") or device.get("last_sync_at")
        result = sync.pull_users(conn, since)
    return 200, result


def device_push(req: Request):
    with get_conn() as conn:
        device = auth.require_device(conn, req.headers)
        result = sync.push_records(conn, device["id"], req.body.get("records", []))
        models.touch_device_sync(conn, device["id"])
    return 200, result


def build_router() -> Router:
    r = Router()
    r.add("GET", "/health", health)

    r.add("POST", "/api/users", create_user)
    r.add("GET", "/api/users", list_users)
    r.add("GET", "/api/users/{id}", get_user)
    r.add("PUT", "/api/users/{id}", update_user)
    r.add("DELETE", "/api/users/{id}", delete_user)

    r.add("POST", "/api/devices", create_device)
    r.add("GET", "/api/devices", list_devices)
    r.add("GET", "/api/devices/{id}", get_device)
    r.add("PUT", "/api/devices/{id}", update_device)
    r.add("DELETE", "/api/devices/{id}", delete_device)

    r.add("GET", "/api/attendance", list_attendance)
    r.add("POST", "/api/attendance", create_attendance)

    r.add("POST", "/api/punch", device_punch)
    r.add("POST", "/api/sync", device_sync)
    r.add("GET", "/api/sync/pull", device_pull)
    r.add("POST", "/api/sync/push", device_push)
    return r


ROUTER = build_router()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "AttendanceServer/1.0"
    protocol_version = "HTTP/1.1"

    # Silence the default noisy logging; override if you want access logs.
    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        pass

    def _handle(self, method: str):
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        try:
            body = self._read_json()
            handler, params = ROUTER.match(method, path)
            req = Request(method, path, self.headers, params, query, body)
            status, payload = handler(req)
        except AppError as exc:
            status, payload = exc.status, exc.to_dict()
        except json.JSONDecodeError:
            status, payload = 400, {"error": "Request body is not valid JSON"}
        except Exception as exc:  # pragma: no cover - safety net
            status, payload = 500, {"error": f"Internal error: {exc}"}

        self._send_json(status, payload)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, url_path: str) -> bool:
        """Serve a file from the web directory. Returns True if handled."""
        file_path = staticfiles.resolve(url_path)
        if file_path is None:
            return False
        try:
            with open(file_path, "rb") as fh:
                body = fh.read()
        except OSError:
            return False

        # index.html should never be cached so UI updates show up immediately.
        cache = "no-cache" if file_path.endswith("index.html") else "max-age=300"
        self.send_response(200)
        self.send_header("Content-Type", staticfiles.content_type_for(file_path))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        # API and health checks go through the router; everything else is
        # treated as a request for the static web client.
        if not path.startswith("/api/") and path not in ("/health", "/api"):
            if self._serve_static(path):
                return
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


def create_server(host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    init_db()
    return ThreadingHTTPServer((host, port), RequestHandler)
