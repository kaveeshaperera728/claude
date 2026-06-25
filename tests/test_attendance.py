"""Test suite for the attendance system (standard-library unittest only).

Covers the data-access layer, the synchronisation logic and the full HTTP
stack via a real server bound to an ephemeral port.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.client import HTTPConnection

# Point the application at an isolated temporary database BEFORE importing it,
# because the default path is resolved at import time.
_TMP_DB = os.path.join(tempfile.mkdtemp(), "test_attendance.db")
os.environ["ATTENDANCE_DB"] = _TMP_DB
os.environ["ADMIN_TOKEN"] = "test-token"

from attendance import models, sync  # noqa: E402
from attendance.db import get_conn, reset_db  # noqa: E402
from attendance.errors import ConflictError, NotFoundError, ValidationError  # noqa: E402
from attendance.server import create_server  # noqa: E402


class ModelTests(unittest.TestCase):
    def setUp(self):
        reset_db()

    def test_create_and_get_user(self):
        with get_conn() as conn:
            user = models.create_user(
                conn, {"employee_code": "E1", "name": "Ann", "pin": "1111"}
            )
            self.assertEqual(user["name"], "Ann")
            self.assertEqual(models.get_user(conn, user["id"])["pin"], "1111")

    def test_duplicate_employee_code_conflicts(self):
        with get_conn() as conn:
            models.create_user(conn, {"employee_code": "E1", "name": "Ann"})
            with self.assertRaises(ConflictError):
                models.create_user(conn, {"employee_code": "E1", "name": "Bob"})

    def test_missing_required_field(self):
        with get_conn() as conn:
            with self.assertRaises(ValidationError):
                models.create_user(conn, {"name": "No Code"})

    def test_soft_delete_keeps_row_but_hides(self):
        with get_conn() as conn:
            u = models.create_user(conn, {"employee_code": "E1", "name": "Ann"})
            models.delete_user(conn, u["id"])
            self.assertEqual(models.list_users(conn), [])
            self.assertEqual(len(models.list_users(conn, include_deleted=True)), 1)

    def test_find_user_for_punch_by_card_and_pin(self):
        with get_conn() as conn:
            models.create_user(
                conn,
                {"employee_code": "E1", "name": "Ann", "pin": "1111",
                 "card_id": "C1"},
            )
            self.assertEqual(
                models.find_user_for_punch(conn, {"card_id": "C1"})["name"], "Ann"
            )
            self.assertEqual(
                models.find_user_for_punch(conn, {"pin": "1111"})["name"], "Ann"
            )
            with self.assertRaises(NotFoundError):
                models.find_user_for_punch(conn, {"card_id": "missing"})

    def test_record_punch_is_idempotent(self):
        with get_conn() as conn:
            u = models.create_user(conn, {"employee_code": "E1", "name": "Ann"})
            r1, c1 = models.record_punch(conn, u["id"], "check_in", record_uuid="x")
            r2, c2 = models.record_punch(conn, u["id"], "check_in", record_uuid="x")
            self.assertTrue(c1)
            self.assertFalse(c2)
            self.assertEqual(r1["id"], r2["id"])

    def test_invalid_punch_type_rejected(self):
        with get_conn() as conn:
            u = models.create_user(conn, {"employee_code": "E1", "name": "Ann"})
            with self.assertRaises(ValidationError):
                models.record_punch(conn, u["id"], "lunch")


class SyncTests(unittest.TestCase):
    def setUp(self):
        reset_db()
        with get_conn() as conn:
            self.user = models.create_user(
                conn, {"employee_code": "E1", "name": "Ann", "pin": "1111"}
            )
            self.device = models.create_device(conn, {"name": "Term1"})

    def test_push_accepts_dedupes_and_rejects(self):
        records = [
            {"uuid": "a", "pin": "1111", "punch_type": "check_in"},
            {"uuid": "a", "pin": "1111", "punch_type": "check_in"},  # dup uuid
            {"uuid": "b", "pin": "0000", "punch_type": "check_in"},  # unknown user
        ]
        with get_conn() as conn:
            result = sync.push_records(conn, self.device["id"], records)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(len(result["rejected"]), 1)

    def test_pull_returns_changes_including_deletes(self):
        with get_conn() as conn:
            before = sync.pull_users(conn, None)["count"]
            models.delete_user(conn, self.user["id"])
        with get_conn() as conn:
            pulled = sync.pull_users(conn, "2000-01-01T00:00:00+00:00")
        names = {u["name"]: u["deleted"] for u in pulled["users"]}
        self.assertEqual(before, 1)
        self.assertEqual(names["Ann"], 1)

    def test_full_sync_updates_last_sync_and_logs(self):
        payload = {"records": [{"uuid": "z", "pin": "1111", "punch_type": "check_in"}]}
        with get_conn() as conn:
            sync.sync(conn, self.device, payload)
        with get_conn() as conn:
            device = models.get_device(conn, self.device["id"])
            log_count = conn.execute("SELECT COUNT(*) c FROM sync_log").fetchone()["c"]
        self.assertIsNotNone(device["last_sync_at"])
        self.assertEqual(log_count, 1)


class HttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_db()
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.admin = {"Authorization": "Bearer test-token"}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        return resp.status, json.loads(data) if data else {}

    def test_health(self):
        status, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_admin_auth_required(self):
        status, _ = self.request("GET", "/api/users")
        self.assertEqual(status, 401)

    def test_unknown_route_404(self):
        status, _ = self.request("GET", "/api/nope", headers=self.admin)
        self.assertEqual(status, 404)

    def test_end_to_end_flow(self):
        # Create a user and a device.
        status, user = self.request(
            "POST", "/api/users",
            {"employee_code": "H1", "name": "Hal", "card_id": "HC1"},
            self.admin,
        )
        self.assertEqual(status, 201)

        status, device = self.request(
            "POST", "/api/devices", {"name": "HTTP Term"}, self.admin
        )
        self.assertEqual(status, 201)
        key = {"X-API-Key": device["api_key"]}

        # Device records a live punch by card.
        status, punch = self.request(
            "POST", "/api/punch", {"card_id": "HC1", "punch_type": "check_in"}, key
        )
        self.assertEqual(status, 201)
        self.assertTrue(punch["created"])

        # Offline batch sync (push + pull), then idempotent re-push.
        batch = {"records": [
            {"uuid": "h-1", "card_id": "HC1", "punch_type": "check_out"},
        ]}
        status, result = self.request("POST", "/api/sync", batch, key)
        self.assertEqual(status, 200)
        self.assertEqual(result["push"]["accepted"], 1)

        status, again = self.request("POST", "/api/sync/push", batch, key)
        self.assertEqual(again["duplicates"], 1)

        # Admin sees all the records for the user.
        status, listing = self.request(
            "GET", f"/api/attendance?user_id={user['id']}", headers=self.admin
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["records"]), 2)

    def test_device_key_required_for_sync(self):
        status, _ = self.request("POST", "/api/sync", {"records": []})
        self.assertEqual(status, 401)

    def _raw_get(self, path):
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode()
        ctype = resp.getheader("Content-Type")
        conn.close()
        return resp.status, ctype, body

    def test_serves_web_index(self):
        status, ctype, body = self._raw_get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("<title>Attendance System</title>", body)

    def test_spa_fallback_for_unknown_page(self):
        status, ctype, _ = self._raw_get("/dashboard")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)

    def test_static_path_traversal_blocked(self):
        status, _, _ = self._raw_get("/../attendance/db.py")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
