from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

from .installations import installation_for_session


class SessionAuthentication(authentication.SessionAuthentication):
    """Session authentication bound to a browser installation.

    On top of DRF's session authentication (including its CSRF enforcement):

    * A session must be bound to an *active* installation. A session with no
      installation (for example one created by the Django admin login) or
      with a revoked one is not accepted by the API. The installation becomes
      ``request.auth``.
    * Unauthenticated requests get 401 rather than DRF's default 403, so the
      SPA can tell "log in again" from "you may not do this".
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, _ = result
        installation = installation_for_session(request._request.session, user)
        if installation is None:
            raise AuthenticationFailed(
                "This session is not linked to an active device. Sign in again.",
                code="device_session_invalid",
            )
        return user, installation

    def authenticate_header(self, request) -> str:
        return "Session"
