"""Security headers for API responses.

Django's SecurityMiddleware covers HSTS, nosniff, referrer and opener policy.
This adds a Content-Security-Policy to JSON API responses, which must never
render as a document. The SPA's own policy is set by the reverse proxy that
serves it (see docs/DEPLOYMENT.md); the admin and the API docs pages are left
alone because they load their own scripts and styles.
"""

API_POLICY = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


class ApiSecurityHeadersMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path
        if path.startswith("/api/") and not path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", API_POLICY)
            response.headers.setdefault("Cache-Control", "no-store")
        return response
