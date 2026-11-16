"""Domain errors and the single API error format.

Every error response has the shape::

    {"code": "machine_readable", "detail": "Human readable.", "errors": {...}}

``errors`` is only present for field-level validation failures.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(Exception):
    """A business rule refused the operation. Raised by service functions."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_operation"

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code


class ConflictError(DomainError):
    """The operation is valid in general but not in the record's current state."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    if isinstance(exc, DomainError):
        return Response({"code": exc.code, "detail": exc.detail}, status=exc.status_code)

    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(as_serializer_error(exc))

    response = drf_exception_handler(exc, context)
    if response is None:
        return None  # unexpected error: let Django log it and return a 500

    if isinstance(exc, exceptions.ValidationError):
        response.data = {
            "code": "validation_error",
            "detail": "The submitted data is not valid.",
            "errors": response.data,
        }
    elif isinstance(exc, exceptions.APIException):
        response.data = {"code": exc.get_codes(), "detail": exc.detail}
    else:  # Http404 / PermissionDenied translated by DRF
        code = "not_found" if response.status_code == 404 else "permission_denied"
        response.data = {"code": code, "detail": response.data.get("detail", "")}
    return response
