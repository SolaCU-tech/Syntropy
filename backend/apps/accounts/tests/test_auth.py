"""Session sign-in (ADR-24): cookie session plus CSRF, enforced on every change."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    # HTTPS requests must carry a same-site Referer for Django's CSRF check.
    return APIClient(enforce_csrf_checks=True, HTTP_REFERER="https://testserver/")


def _csrf(client) -> str:
    response = client.get(reverse("auth-session"), secure=True)
    return response.cookies["csrftoken"].value


def test_session_reports_signed_out_and_sets_csrf_cookie(client):
    response = client.get(reverse("auth-session"), secure=True)
    assert response.json() == {"authenticated": False, "user": None}
    assert "csrftoken" in response.cookies


def test_sign_in_and_out(client, make_user):
    make_user("ade", first_name="Ade")
    token = _csrf(client)
    signed_in = client.post(
        reverse("auth-login"),
        {"username": "ade", "password": "pw"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        secure=True,
    )
    assert signed_in.status_code == 200, signed_in.json()
    assert signed_in.json()["user"]["first_name"] == "Ade"
    assert client.get(reverse("auth-session"), secure=True).json()["authenticated"] is True
    assert client.get(reverse("workspace-list"), secure=True).status_code == 200

    token = client.cookies["csrftoken"].value
    out = client.post(reverse("auth-logout"), HTTP_X_CSRFTOKEN=token, secure=True)
    assert out.status_code == 204, out.content
    assert client.get(reverse("workspace-list"), secure=True).status_code == 403


def test_wrong_password(client, make_user):
    make_user("ade")
    response = client.post(
        reverse("auth-login"),
        {"username": "ade", "password": "nope"},
        format="json",
        HTTP_X_CSRFTOKEN=_csrf(client),
        secure=True,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_login"


def test_changes_without_the_csrf_token_are_refused(client, make_user):
    make_user("ade")
    _csrf(client)
    client.login(username="ade", password="pw")  # noqa: S106
    response = client.post(reverse("auth-logout"), secure=True)
    assert response.status_code == 403


def test_sign_in_needs_the_csrf_token(client, make_user):
    make_user("ade")
    _csrf(client)
    response = client.post(
        reverse("auth-login"), {"username": "ade", "password": "pw"}, format="json", secure=True
    )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
