"""Shared pytest fixtures for the whole backend."""

import copy

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.schema_registry.examples import load_retail_ssd
from apps.tenancy.models import Membership
from apps.tenancy.services import create_workspace


@pytest.fixture
def make_user(db):
    def make(username: str = "ade", **extra):
        return get_user_model().objects.create_user(username=username, password="pw", **extra)  # noqa: S106

    return make


@pytest.fixture
def owner(make_user):
    return make_user("owner")


@pytest.fixture
def workspace(owner):
    return create_workspace(owner, "Ade's Provisions")


@pytest.fixture
def add_member(make_user, workspace):
    def add(role: str, username: str | None = None):
        user = make_user(username or f"{role}_user")
        Membership.objects.create(user=user, workspace=workspace, role=role)
        return user

    return add


@pytest.fixture
def client_for():
    def make(user=None) -> APIClient:
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    return make


_RETAIL = load_retail_ssd()


@pytest.fixture
def retail() -> dict:
    """A fresh, mutable copy of the hand-written retail SSD."""
    return copy.deepcopy(_RETAIL)
