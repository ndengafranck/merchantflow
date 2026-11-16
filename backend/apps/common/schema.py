"""OpenAPI description of the session-cookie authentication scheme."""

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.SessionAuthentication"
    name = "sessionCookie"

    def get_security_definition(self, auto_schema) -> dict:
        return {"type": "apiKey", "in": "cookie", "name": settings.SESSION_COOKIE_NAME}
