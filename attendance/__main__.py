"""Run the attendance server: ``python -m attendance``.

Environment variables:
  ATTENDANCE_HOST  bind host (default 0.0.0.0)
  ATTENDANCE_PORT  bind port (default 8080)
  ATTENDANCE_DB    sqlite database path (default ./attendance.db)
  ADMIN_TOKEN      bearer token for admin endpoints (default 'admin-secret')
"""

from __future__ import annotations

import errno
import os
import sys

from .auth import admin_token
from .server import create_server


def main() -> None:
    host = os.environ.get("ATTENDANCE_HOST", "0.0.0.0")
    port = int(os.environ.get("ATTENDANCE_PORT", "8080"))

    try:
        server = create_server(host, port)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            sys.stderr.write(
                f"\nERROR: port {port} is already in use by another program.\n"
                f"Another service (not this app) is occupying it, so requests to\n"
                f"http://localhost:{port} reach that program instead.\n\n"
                f"Fix: start on a free port, e.g.\n"
                f"    ATTENDANCE_PORT=8090 python -m attendance\n"
                f"then open http://localhost:8090 — or stop the program on "
                f"port {port}.\n"
            )
            raise SystemExit(1) from exc
        raise

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
