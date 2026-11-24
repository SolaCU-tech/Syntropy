"""Guards for foundation decisions that later phases rely on."""

from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework import serializers
from rest_framework.test import APIClient


def test_database_is_postgresql():
    # ADR-03: PostgreSQL only. JSONB storage in Phase 2 depends on it.
    assert connection.vendor == "postgresql"


def test_custom_user_model_is_active():
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert get_user_model()._meta.label == "accounts.User"


def test_decimals_serialize_as_strings():
    # ADR-25: money never travels as a float.
    field = serializers.DecimalField(max_digits=14, decimal_places=2)
    assert field.to_representation(Decimal("1200.50")) == "1200.50"


def test_api_requires_authentication_by_default():
    # Endpoints must opt out explicitly (like health); everything else needs a session.
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == [
        "rest_framework.authentication.SessionAuthentication"
    ]


@pytest.mark.django_db
def test_api_schema_is_not_public_outside_debug():
    response = APIClient().get("/api/schema/")
    assert response.status_code == 403


def test_celery_ping_task_runs():
    from apps.core.tasks import ping

    assert ping.apply().get() == "pong"
