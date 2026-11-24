"""Workspace and schema endpoints: membership is checked on every request."""

import uuid

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.schema_registry import registry
from apps.tenancy.models import Membership, Role, Workspace
from apps.tenancy.services import create_workspace

pytestmark = pytest.mark.django_db


def schema_url(workspace_id) -> str:
    return reverse("workspace-schema", kwargs={"workspace_id": workspace_id})


def detail_url(workspace_id) -> str:
    return reverse("workspace-detail", kwargs={"workspace_id": workspace_id})


@pytest.fixture
def published(workspace, owner, retail):
    return registry.publish(registry.create_draft(workspace, retail, created_by=owner))


def test_anonymous_requests_are_refused_with_the_standard_error_shape(client_for, workspace):
    response = client_for().get(reverse("workspace-list"))

    assert response.status_code == 403
    assert response.json() == {
        "code": "not_authenticated",
        "message": "Authentication credentials were not provided.",
    }


def test_create_workspace_makes_the_caller_its_owner(client_for, owner):
    response = client_for(owner).post(
        reverse("workspace-list"), {"name": "Mama Ngozi Foods"}, format="json"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Mama Ngozi Foods"
    assert body["slug"] == "mama-ngozi-foods"
    assert body["role"] == "owner"
    assert body["status"] == "setup"
    assert body["timezone"] == "Africa/Lagos"
    assert body["currency"] == "NGN"
    workspace = Workspace.objects.get(pk=body["id"])
    assert Membership.objects.get(workspace=workspace).user == owner


def test_create_workspace_validation_errors_use_the_standard_shape(client_for, owner):
    response = client_for(owner).post(reverse("workspace-list"), {}, format="json")

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid"
    assert "name" in body["details"]


def test_list_shows_only_my_workspaces_with_my_role(client_for, workspace, owner, add_member):
    editor = add_member(Role.EDITOR)
    create_workspace(owner, "Second shop")

    mine = client_for(owner).get(reverse("workspace-list")).json()
    theirs = client_for(editor).get(reverse("workspace-list")).json()

    assert sorted(w["name"] for w in mine) == ["Ade's Provisions", "Second shop"]
    assert theirs == [{**next(w for w in mine if w["id"] == str(workspace.id)), "role": "editor"}]


def test_detail_for_a_member(client_for, workspace, add_member):
    viewer = add_member(Role.VIEWER)

    response = client_for(viewer).get(detail_url(workspace.id))

    assert response.status_code == 200
    assert response.json()["role"] == "viewer"


@pytest.mark.parametrize("role", list(Role))
def test_every_role_can_read_the_active_schema(client_for, workspace, published, add_member, role):
    user = add_member(role, username=f"u_{role}")

    response = client_for(user).get(schema_url(workspace.id))

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["status"] == "published"
    assert body["workspace_id"] == str(workspace.id)
    assert [t["key"] for t in body["tables"]] == ["customers", "products", "sales"]


def test_schema_endpoint_is_read_only(client_for, workspace, owner, published):
    client = client_for(owner)

    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)(schema_url(workspace.id), {}).status_code == 405


def test_schema_404_when_nothing_is_published(client_for, workspace, owner):
    response = client_for(owner).get(schema_url(workspace.id))

    assert response.status_code == 404
    assert response.json()["code"] == "no_active_schema"


def test_another_business_cannot_read_this_schema(client_for, workspace, published, make_user):
    outsider = make_user("outsider")
    create_workspace(outsider, "Outsider's shop")

    for url in (schema_url(workspace.id), detail_url(workspace.id)):
        response = client_for(outsider).get(url)
        assert response.status_code == 404
        assert response.json()["code"] == "workspace_not_found"


def test_unknown_workspace_looks_the_same_as_a_forbidden_one(client_for, owner):
    response = client_for(owner).get(schema_url(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_a_user_can_hold_only_one_membership_per_workspace(workspace, owner):
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=owner, workspace=workspace, role=Role.VIEWER)


def test_roles_outside_the_four_are_rejected_by_the_database(workspace, make_user):
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=make_user("x"), workspace=workspace, role="superhero")
