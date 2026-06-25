"""Seed the database with sample users and devices for local testing.

Usage:  python seed.py
The admin token and any issued device API keys are printed at the end.
"""

from __future__ import annotations

from attendance import auth, models
from attendance.db import get_conn, reset_db

SAMPLE_USERS = [
    {"employee_code": "E001", "name": "Alice Ng", "email": "alice@example.com",
     "pin": "1234", "card_id": "CARD-001"},
    {"employee_code": "E002", "name": "Bob Silva", "email": "bob@example.com",
     "pin": "2345", "card_id": "CARD-002"},
    {"employee_code": "E003", "name": "Carla Mendes", "email": "carla@example.com",
     "pin": "3456", "card_id": "CARD-003"},
]

SAMPLE_DEVICES = [
    {"name": "Front Door Terminal", "location": "Main Entrance"},
    {"name": "Warehouse Terminal", "location": "Warehouse Bay 2"},
]


def main() -> None:
    reset_db()
    created_devices = []
    with get_conn() as conn:
        for u in SAMPLE_USERS:
            models.create_user(conn, u)
        for d in SAMPLE_DEVICES:
            created_devices.append(models.create_device(conn, d))

    print("Seed complete.")
    print(f"Admin token: {auth.admin_token()}")
    print("Devices and their API keys:")
    for d in created_devices:
        print(f"  - {d['name']:<24} id={d['id']}  api_key={d['api_key']}")


if __name__ == "__main__":
    main()
