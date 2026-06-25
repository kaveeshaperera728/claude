"""Domain errors used across the application.

These are translated into HTTP responses by the server layer.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for application errors with an associated HTTP status."""

    status = 400

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status

    def to_dict(self) -> dict:
        return {"error": self.message}


class ValidationError(AppError):
    status = 400


class NotFoundError(AppError):
    status = 404


class ConflictError(AppError):
    status = 409


class AuthError(AppError):
    status = 401
