"""Run the attendance server: ``python -m attendance``.

Environment variables:
  ATTENDANCE_HOST  bind host (default 0.0.0.0)
  ATTENDANCE_PORT  bind port (default 8080)
  ATTENDANCE_DB    sqlite database path (default ./attendance.db)
  ADMIN_TOKEN      bearer token for admin endpoints (default 'admin-secret')
"""

from __future__ import annotations

import os

from .auth import admin_token
from .server import create_server


def main() -> None:
    host = os.environ.get("ATTENDANCE_HOST", "0.0.0.0")
    port = int(os.environ.get("ATTENDANCE_PORT", "8080"))

    server = create_server(host, port)
    using_default = admin_token() == "admin-secret"

    print(f"Attendance server listening on http://{host}:{port}")
    if using_default:
        print("WARNING: using the default ADMIN_TOKEN ('admin-secret'). "
              "Set ADMIN_TOKEN in production.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
