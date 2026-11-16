from rest_framework import authentication


class SessionAuthentication(authentication.SessionAuthentication):
    """Session authentication that answers unauthenticated requests with 401.

    DRF's stock class sends no ``WWW-Authenticate`` header, which makes DRF
    downgrade "not logged in" to 403. The SPA needs to tell "log in again"
    (401) apart from "you may not do this" (403). CSRF enforcement for
    authenticated requests is inherited unchanged.
    """

    def authenticate_header(self, request) -> str:
        return "Session"
