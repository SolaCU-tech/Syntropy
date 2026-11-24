import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_reports_ok_when_database_is_reachable():
    response = APIClient().get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_degraded_when_database_fails(monkeypatch):
    from apps.core import views

    class BrokenConnection:
        def cursor(self):
            raise RuntimeError("database down")

    monkeypatch.setattr(views, "connection", BrokenConnection())

    response = APIClient().get(reverse("health"))

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
