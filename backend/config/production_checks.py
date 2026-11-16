"""Settings that must hold whenever DJANGO_DEBUG is false.

``settings.py`` calls ``production_problems`` and refuses to start if it
returns anything, so an unsafe production configuration fails at boot rather
than being discovered later. The function is pure so every rule is unit tested
(tests/test_production_settings.py).
"""

from dataclasses import dataclass

MIN_SECRET_KEY_LENGTH = 50
MIN_SECRET_KEY_UNIQUE_CHARACTERS = 5  # same thresholds as Django's security.W009
MIN_HSTS_SECONDS = 60 * 60 * 24 * 180


@dataclass(frozen=True)
class SecuritySettings:
    secret_key: str
    secure_cookies: bool
    allowed_hosts: list[str]
    csrf_trusted_origins: list[str]
    trusted_proxy_count: int
    trusted_proxy_count_is_explicit: bool
    ssl_redirect: bool
    hsts_seconds: int
    admin_enabled: bool
    admin_path: str


def production_problems(s: SecuritySettings) -> list[str]:
    problems = []
    if (
        s.secret_key.startswith(("insecure-", "django-insecure-"))
        or len(s.secret_key) < MIN_SECRET_KEY_LENGTH
        or len(set(s.secret_key)) < MIN_SECRET_KEY_UNIQUE_CHARACTERS
    ):
        problems.append(
            f"DJANGO_SECRET_KEY must be a random value of at least {MIN_SECRET_KEY_LENGTH} "
            "characters, not the development placeholder."
        )
    if not s.secure_cookies:
        problems.append("DJANGO_SECURE_COOKIES must be true: cookies would be sent over HTTP.")
    if not s.allowed_hosts or "*" in s.allowed_hosts:
        problems.append("DJANGO_ALLOWED_HOSTS must list the site's host names (no '*').")
    insecure_origins = [o for o in s.csrf_trusted_origins if not o.startswith("https://")]
    if insecure_origins:
        problems.append(
            "DJANGO_CSRF_TRUSTED_ORIGINS must all be https:// origins: "
            + ", ".join(insecure_origins)
        )
    if not s.trusted_proxy_count_is_explicit:
        problems.append(
            "DJANGO_TRUSTED_PROXY_COUNT must be set explicitly to the number of reverse "
            "proxies in front of Django."
        )
    elif s.trusted_proxy_count < 1:
        problems.append(
            "DJANGO_TRUSTED_PROXY_COUNT must be at least 1: TLS has to be terminated by a "
            "reverse proxy in front of Django."
        )
    if not s.ssl_redirect:
        problems.append("DJANGO_SECURE_SSL_REDIRECT must be true.")
    if s.hsts_seconds < MIN_HSTS_SECONDS:
        problems.append(f"DJANGO_HSTS_SECONDS must be at least {MIN_HSTS_SECONDS}.")
    if s.admin_enabled and s.admin_path.strip("/") == "admin":
        problems.append(
            "The Django admin is enabled at the default path. Disable it "
            "(DJANGO_ADMIN_ENABLED=false) or set a non-default DJANGO_ADMIN_PATH and restrict "
            "access to it at the reverse proxy."
        )
    return problems
