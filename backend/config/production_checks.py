"""Start-up rules for each DJANGO_ENVIRONMENT.

``settings.py`` refuses to start if these return anything:

* ``production_problems`` whenever DJANGO_ENVIRONMENT is ``production``,
  regardless of DEBUG (production with DEBUG on is itself refused);
* ``non_production_problems`` otherwise: development and test servers may
  only answer to local host names, so a production deployment that was
  mislabelled ``development`` fails instead of running without the
  production rules.

The functions are pure so every rule is unit tested
(tests/test_production_settings.py).
"""

import ipaddress
from dataclasses import dataclass

MIN_SECRET_KEY_LENGTH = 50
MIN_SECRET_KEY_UNIQUE_CHARACTERS = 5  # same thresholds as Django's security.W009
MIN_HSTS_SECONDS = 60 * 60 * 24 * 180


@dataclass(frozen=True)
class SecuritySettings:
    debug: bool
    reads_dot_env: bool
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
    if s.debug:
        problems.append("DJANGO_DEBUG must be false in production.")
    if s.reads_dot_env:
        problems.append(
            "DJANGO_READ_DOT_ENV must be false in production: configuration comes from the "
            "deployment's environment, never from a file that may be left on the server."
        )
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


_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".test", ".example", ".invalid")
_LOCAL_NAMES = {"localhost", "testserver", "0.0.0.0"}  # noqa: S104 - a name, not a bind


def is_local_host(host: str) -> bool:
    """True for names and addresses that cannot be a public production site."""
    name = host.strip().lower().lstrip(".").strip("[]")
    if name == "*":
        return False
    if (
        name in _LOCAL_NAMES
        or name.endswith(_LOCAL_SUFFIXES)
        or "." not in name
        and ":" not in name
    ):
        return True  # single-label names (e.g. a docker service) are not public DNS
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def non_production_problems(
    *, environment: str, allowed_hosts: list[str], allow_non_local_hosts: bool
) -> list[str]:
    if allow_non_local_hosts:
        return []
    public = [h for h in allowed_hosts if h == "*" or not is_local_host(h)]
    if not public:
        return []
    return [
        f"DJANGO_ALLOWED_HOSTS includes {', '.join(public)}, which is not a local name, but "
        f"DJANGO_ENVIRONMENT is {environment}. If this is a production deployment set "
        "DJANGO_ENVIRONMENT=production (and satisfy the production rules). For a deliberate "
        "non-local development server set DJANGO_ALLOW_NON_LOCAL_HOSTS=true."
    ]
