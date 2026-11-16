from unittest import mock

from django.db import DatabaseError
from rest_framework.test import APIClient


def test_health_reports_ok_with_database(db):
    response = APIClient().get("/api/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_503_when_database_is_unreachable(db):
    with mock.patch("apps.common.views.connection.cursor", side_effect=DatabaseError("down")):
        response = APIClient().get("/api/health/")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
