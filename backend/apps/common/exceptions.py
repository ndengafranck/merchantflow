"""Domain errors raised by service functions.

This module must stay free of any HTTP or framework import: business code
states *what* went wrong, and ``api_errors`` decides how that looks over HTTP.
"""


class DomainError(Exception):
    """A business rule refused the operation."""

    code = "invalid_operation"

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code


class ConflictError(DomainError):
    """The operation is valid in general but not in the record's current state."""

    code = "conflict"


class NotPermittedError(DomainError):
    """The actor is not allowed to perform the operation."""

    code = "permission_denied"


class NotFoundError(DomainError):
    """The record does not exist, or not where the actor is allowed to look."""

    code = "not_found"
