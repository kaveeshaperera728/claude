"""Static file serving for the bundled web UI.

The web client is plain HTML/CSS/JS (no build step, no third-party
dependencies) and is served from the ``web/`` directory that sits next to the
``attendance`` package.
"""

from __future__ import annotations

import os

# web/ lives at the repository root, one level above this package.
WEB_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, "web")
)

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".map": "application/json",
}


def content_type_for(path: str) -> str:
    _, ext = os.path.splitext(path)
    return CONTENT_TYPES.get(ext.lower(), "application/octet-stream")


def resolve(url_path: str) -> str | None:
    """Map a URL path to a safe file inside WEB_DIR.

    Returns the absolute file path, or ``None`` if it escapes WEB_DIR or does
    not exist. Unknown non-asset paths fall back to ``index.html`` so the
    single-page client can handle its own routing.
    """
    clean = url_path.lstrip("/")
    if clean in ("", "/"):
        clean = "index.html"

    candidate = os.path.normpath(os.path.join(WEB_DIR, clean))
    # Prevent path traversal outside the web root.
    if not candidate.startswith(WEB_DIR):
        return None

    if os.path.isfile(candidate):
        return candidate

    # SPA fallback: only for paths that don't look like a static asset.
    if "." not in os.path.basename(clean):
        index = os.path.join(WEB_DIR, "index.html")
        return index if os.path.isfile(index) else None

    return None
