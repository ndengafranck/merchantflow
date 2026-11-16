"""F-06: unsafe production settings are refused at start-up."""

import os
import secrets
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from django.test import Client, override_settings

from config.production_checks import SecuritySettings, production_problems

BACKEND = Path(__file__).resolve().parent.parent

SAFE = SecuritySettings(
    secret_key=secrets.token_urlsafe(64),
    secure_cookies=True,
    allowed_hosts=["app.merchantflow.example"],
    csrf_trusted_origins=["https://app.merchantflow.example"],
    trusted_proxy_count=1,
    trusted_proxy_count_is_explicit=True,
    ssl_redirect=True,
    hsts_seconds=31536000,
    admin_enabled=False,
    admin_path="admin/",
)


def test_a_safe_configuration_has_no_problems():
    assert production_problems(SAFE) == []


@pytest.mark.parametrize(
    ("change", "mentions"),
    [
        ({"secret_key": "insecure-dev-only-change-me"}, "DJANGO_SECRET_KEY"),
        ({"secret_key": "short"}, "DJANGO_SECRET_KEY"),
        ({"secret_key": "s" * 64}, "DJANGO_SECRET_KEY"),
        ({"secure_cookies": False}, "DJANGO_SECURE_COOKIES"),
        ({"allowed_hosts": []}, "DJANGO_ALLOWED_HOSTS"),
        ({"allowed_hosts": ["*"]}, "DJANGO_ALLOWED_HOSTS"),
        ({"csrf_trusted_origins": ["http://app.example"]}, "DJANGO_CSRF_TRUSTED_ORIGINS"),
        ({"trusted_proxy_count_is_explicit": False}, "set explicitly"),
        ({"trusted_proxy_count": 0}, "at least 1"),
        ({"ssl_redirect": False}, "DJANGO_SECURE_SSL_REDIRECT"),
        ({"hsts_seconds": 0}, "DJANGO_HSTS_SECONDS"),
        ({"admin_enabled": True, "admin_path": "admin/"}, "default path"),
    ],
)
def test_each_unsafe_setting_is_reported(change, mentions):
    problems = production_problems(replace(SAFE, **change))
    assert len(problems) == 1
    assert mentions in problems[0]


def test_admin_on_a_private_path_is_accepted():
    assert production_problems(replace(SAFE, admin_enabled=True, admin_path="ops-7f3a/")) == []


# --- The real settings module, in a separate process -------------------------------------


def production_env(**overrides) -> dict:
    """The documented production reference, with overrides; no .env file read."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "API_DOCS"))}
    for line in (BACKEND / ".env.production.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            env[key] = value
    env["DJANGO_SECRET_KEY"] = secrets.token_urlsafe(64)
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def manage(*args, **overrides):
    return subprocess.run(  # noqa: S603 - our own interpreter and manage.py
        [sys.executable, "manage.py", *args],
        cwd=BACKEND,
        env=production_env(**overrides),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_documented_production_settings_pass_the_deploy_check():
    result = manage("check", "--deploy", "--fail-level", "WARNING")
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.mark.parametrize(
    ("overrides", "mentions"),
    [
        # Assessment: this combination started without any warning.
        ({"DJANGO_SECURE_COOKIES": "false"}, "DJANGO_SECURE_COOKIES"),
        ({"DJANGO_TRUSTED_PROXY_COUNT": None}, "DJANGO_TRUSTED_PROXY_COUNT"),
        ({"DJANGO_SECRET_KEY": "insecure-dev-only-change-me"}, "DJANGO_SECRET_KEY"),
        ({"DJANGO_SECURE_SSL_REDIRECT": "false"}, "DJANGO_SECURE_SSL_REDIRECT"),
        ({"DJANGO_ADMIN_ENABLED": "true"}, "default path"),
    ],
)
def test_unsafe_production_settings_stop_the_application_starting(overrides, mentions):
    result = manage("check", **overrides)
    assert result.returncode != 0
    assert "Unsafe production settings" in result.stderr
    assert mentions in result.stderr


def test_debug_mode_is_not_subject_to_the_production_rules():
    result = manage("check", DJANGO_DEBUG="true", DJANGO_SECURE_COOKIES="false")
    assert result.returncode == 0, result.stderr


# --- Response headers ----------------------------------------------------------------


def test_api_responses_carry_a_restrictive_content_security_policy(db):
    for path in ("/api/health/", "/api/v1/auth/me/"):
        response = Client().get(path)
        assert "default-src 'none'" in response["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
        assert response["Cache-Control"] == "no-store"
        assert response["X-Content-Type-Options"] == "nosniff"


@override_settings(SECURE_SSL_REDIRECT=True)
def test_https_redirect_exempts_only_the_health_check(db):
    assert Client().get("/api/v1/auth/me/").status_code == 301
    assert Client().get("/api/health/").status_code == 200
