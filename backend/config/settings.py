"""Django settings for MerchantFlow.

Every deployment-specific value comes from the environment (see .env.example).
There is deliberately a single settings module: environments differ by
configuration, not by code.
"""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
# A local .env file is a development convenience; real environment variables
# win. Deployments (and tests of production settings) set
# DJANGO_READ_DOT_ENV=false so a stray file cannot fill in missing values.
READ_DOT_ENV = env.bool("DJANGO_READ_DOT_ENV", default=True)
if READ_DOT_ENV:
    environ.Env.read_env(BASE_DIR / ".env")

# Which kind of deployment this is. Required, with no default, so a server can
# never fall into a lax mode by omission. Security behaviour follows this, not
# DEBUG: production rules apply whenever it is "production", even if someone
# turns DEBUG on (which production then refuses).
ENVIRONMENTS = ("development", "test", "production")
ENVIRONMENT = env.str("DJANGO_ENVIRONMENT", default="")
if ENVIRONMENT not in ENVIRONMENTS:
    raise ImproperlyConfigured(
        "Set DJANGO_ENVIRONMENT to one of: " + ", ".join(ENVIRONMENTS) + ". "
        "For local work add DJANGO_ENVIRONMENT=development to backend/.env "
        f"(got {ENVIRONMENT!r})."
    )
IS_PRODUCTION = ENVIRONMENT == "production"

DEBUG = env.bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env.str("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "apps.common.admin_config.MerchantFlowAdminConfig",  # django.contrib.admin, protected
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.common",
    "apps.accounts",
    "apps.workspaces",
    "apps.devices",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.ApiSecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database -----------------------------------------------------------
# PostgreSQL is the only supported database: constraints and locking
# behaviour that protect business data are not certified on anything else.
DATABASES = {"default": env.db("DATABASE_URL")}
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("DATABASE_URL must point to a PostgreSQL database.")
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Identity -----------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Sessions, cookies and CSRF ------------------------------------------
# The browser authenticates with a server-side session referenced by an
# HttpOnly cookie. JavaScript can never read the session identifier; it only
# reads the CSRF token, which is useless without the session cookie.
SECURE_COOKIES = env.bool("DJANGO_SECURE_COOKIES", default=IS_PRODUCTION)
SESSION_ENGINE = "apps.accounts.session_store"  # sessions know their user and device
SESSION_COOKIE_NAME = "mf_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = SECURE_COOKIES
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
# Identifies the browser installation across logins. An identifier, not a
# credential: it is only read at login, after the password has been verified.
DEVICE_COOKIE_NAME = "mf_device"
DEVICE_COOKIE_AGE = 60 * 60 * 24 * 400
CSRF_COOKIE_NAME = "mf_csrftoken"
CSRF_COOKIE_HTTPONLY = False  # the SPA echoes it in the X-CSRFToken header
CSRF_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
CSRF_FAILURE_VIEW = "apps.common.views.csrf_failure"

# --- Transport security --------------------------------------------------
# On by default in production; production_checks refuses to turn them off.
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=IS_PRODUCTION)
SECURE_HSTS_SECONDS = env.int(
    "DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 365 if IS_PRODUCTION else 0
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("DJANGO_HSTS_PRELOAD", default=False)
# Health checks come from the load balancer over plain HTTP inside the network.
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- Reverse proxy and sign-in protection ------------------------------------
# How many reverse proxies in front of Django are trusted to append the client
# address to X-Forwarded-For. 0 = ignore the header (development, or Django
# reached directly). Must match the real deployment exactly: too high lets
# clients forge their address, too low makes every client look like the proxy.
TRUSTED_PROXY_COUNT = env.int("DJANGO_TRUSTED_PROXY_COUNT", default=0)
if TRUSTED_PROXY_COUNT > 0:
    # The outermost trusted proxy terminates TLS and says so in this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Failed sign-in attempts allowed per window (see apps/accounts/login_protection.py).
LOGIN_PROTECTION = {
    "WINDOW_SECONDS": env.int("LOGIN_WINDOW_SECONDS", default=15 * 60),
    "ACCOUNT_AND_ADDRESS": env.int("LOGIN_MAX_FAILURES_ACCOUNT_ADDRESS", default=5),
    "ACCOUNT": env.int("LOGIN_MAX_FAILURES_ACCOUNT", default=20),
    "ADDRESS": env.int("LOGIN_MAX_FAILURES_ADDRESS", default=100),
    # A browser that already signed in to the account (device cookie) has only
    # this limit, and is not blocked by the account or address limits above.
    "KNOWN_BROWSER": env.int("LOGIN_MAX_FAILURES_KNOWN_BROWSER", default=10),
}

# --- Django admin ------------------------------------------------------------
ADMIN_ENABLED = env.bool("DJANGO_ADMIN_ENABLED", default=DEBUG and not IS_PRODUCTION)
ADMIN_PATH = env.str("DJANGO_ADMIN_PATH", default="admin/")

# --- API ------------------------------------------------------------------
API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=DEBUG and not IS_PRODUCTION)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.SessionAuthentication"],
    # Deny by default: a view must opt out explicitly to be public.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.api_errors.api_exception_handler",
    # Same trust rule as apps.common.net.client_ip, for any DRF throttle added later.
    "NUM_PROXIES": TRUSTED_PROXY_COUNT,
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "MerchantFlow API",
    "DESCRIPTION": "Social commerce and affiliate sales management.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]+",
    "ENUM_NAME_OVERRIDES": {
        "WorkspaceStatusEnum": "apps.workspaces.models.WorkspaceStatus",
        "MembershipStatusEnum": "apps.workspaces.models.MembershipStatus",
        # Installations and workspace devices share the active/revoked choice set.
        "DeviceStatusEnum": "apps.workspaces.models.WorkspaceDeviceStatus",
    },
}

# --- Production safeguards ----------------------------------------------------
# Submitting the domain to the browsers' HSTS preload list is a one-way
# operational decision, so it is opt-in (DJANGO_HSTS_PRELOAD) rather than
# a deploy-check failure.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

from config.production_checks import (  # noqa: E402
    SecuritySettings,
    non_production_problems,
    production_problems,
)

if IS_PRODUCTION:
    _problems = production_problems(
        SecuritySettings(
            debug=DEBUG,
            reads_dot_env=READ_DOT_ENV,
            secret_key=SECRET_KEY,
            secure_cookies=SECURE_COOKIES,
            allowed_hosts=ALLOWED_HOSTS,
            csrf_trusted_origins=CSRF_TRUSTED_ORIGINS,
            trusted_proxy_count=TRUSTED_PROXY_COUNT,
            trusted_proxy_count_is_explicit="DJANGO_TRUSTED_PROXY_COUNT" in env.ENVIRON,
            ssl_redirect=SECURE_SSL_REDIRECT,
            hsts_seconds=SECURE_HSTS_SECONDS,
            admin_enabled=ADMIN_ENABLED,
            admin_path=ADMIN_PATH,
        )
    )
else:
    _problems = non_production_problems(
        environment=ENVIRONMENT,
        allowed_hosts=ALLOWED_HOSTS,
        allow_non_local_hosts=env.bool("DJANGO_ALLOW_NON_LOCAL_HOSTS", default=False),
    )
if _problems:
    raise ImproperlyConfigured(
        f"Unsafe settings for DJANGO_ENVIRONMENT={ENVIRONMENT}:\n- " + "\n- ".join(_problems)
    )

# --- Internationalisation ---------------------------------------------------
LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"  # stored and exchanged in UTC; clients localise for display
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env.str("DJANGO_LOG_LEVEL", default="INFO")},
}
