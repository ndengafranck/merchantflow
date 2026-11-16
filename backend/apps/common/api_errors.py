"""The single API error format, and the translation of domain errors to HTTP.

Every error response has the shape::

    {"code": "machine_readable", "detail": "Human readable.", "errors": {...}}

``errors`` is only present for field-level validation failures.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler as drf_exception_handler

from .exceptions import ConflictError, DomainError, NotFoundError, NotPermittedError

# Most specific first; DomainError itself is the fallback.
_DOMAIN_STATUS = [
    (NotPermittedError, status.HTTP_403_FORBIDDEN),
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),
    (DomainError, status.HTTP_400_BAD_REQUEST),
]


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    if isinstance(exc, DomainError):
        http_status = next(code for kind, code in _DOMAIN_STATUS if isinstance(exc, kind))
        return Response({"code": exc.code, "detail": exc.detail}, status=http_status)

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
