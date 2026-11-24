"""The workspace resolver is the tenant-isolation checkpoint: test it directly."""

import uuid

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.tenancy.models import Role, Workspace
from apps.tenancy.permissions import ROLE_PERMISSIONS, Action, role_allows
from apps.tenancy.resolver import (
    WorkspaceNotFound,
    WorkspacePermissionDenied,
    resolve_workspace,
)
from apps.tenancy.services import create_workspace

pytestmark = pytest.mark.django_db


def test_member_gets_a_context_with_their_role(workspace, owner):
    context = resolve_workspace(owner, workspace.id)

    assert context.workspace == workspace
    assert context.role == Role.OWNER


def test_workspace_id_may_be_a_string(workspace, owner):
    assert resolve_workspace(owner, str(workspace.id)).workspace == workspace


def test_non_member_is_told_the_workspace_does_not_exist(workspace, make_user):
    stranger = make_user("stranger")

    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(stranger, workspace.id)


def test_member_of_another_workspace_cannot_reach_this_one(workspace, make_user):
    other_owner = make_user("other")
    create_workspace(other_owner, "Other shop")

    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(other_owner, workspace.id)


@pytest.mark.parametrize("workspace_id", [uuid.uuid4(), "not-a-uuid", ""])
def test_unknown_or_malformed_ids_look_the_same_as_forbidden_ones(owner, workspace_id):
    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(owner, workspace_id)


def test_anonymous_and_inactive_users_are_refused(workspace, owner):
    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(AnonymousUser(), workspace.id)

    owner.is_active = False
    owner.save()
    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(owner, workspace.id)


def test_archived_workspaces_are_not_resolved(workspace, owner):
    Workspace.objects.filter(pk=workspace.pk).update(status=Workspace.Status.ARCHIVED)

    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(owner, workspace.id)


def test_require_raises_when_the_role_lacks_the_action(workspace, add_member):
    viewer = add_member(Role.VIEWER)
    context = resolve_workspace(viewer, workspace.id)

    context.require(Action.VIEW_SCHEMA)
    with pytest.raises(WorkspacePermissionDenied):
        context.require(Action.EDIT_RECORDS)


# The permission matrix from spec section 5 (Recommended until confirmed).

MATRIX = {
    Action.MANAGE_BILLING: {"owner"},
    Action.DELETE_WORKSPACE: {"owner"},
    Action.APPROVE_SCHEMA_CHANGES: {"owner"},
    Action.ACTIVATE_WORKSPACE: {"owner", "admin"},
    Action.MANAGE_MEMBERS: {"owner", "admin"},
    Action.IMPORT_DATA: {"owner", "admin"},
    Action.EDIT_STRUCTURE_LABELS: {"owner", "admin"},
    Action.EDIT_RECORDS: {"owner", "admin", "editor"},
    Action.DELETE_ANY_RECORD: {"owner", "admin"},
    Action.DELETE_OWN_RECORDS: {"owner", "admin", "editor"},
    Action.ASK_AND_RUN_REPORTS: {"owner", "admin", "editor", "viewer"},
    Action.SAVE_REPORTS: {"owner", "admin", "editor"},
    Action.EXPORT: {"owner", "admin"},
    Action.VIEW_WORKSPACE: {"owner", "admin", "editor", "viewer"},
    Action.VIEW_SCHEMA: {"owner", "admin", "editor", "viewer"},
}


def test_matrix_covers_every_action():
    assert set(MATRIX) == set(Action)


@pytest.mark.parametrize("action", list(Action))
@pytest.mark.parametrize("role", list(Role))
def test_permission_matrix_matches_the_spec(role, action):
    assert role_allows(role, action) is (role.value in MATRIX[action])


def test_unknown_role_has_no_permissions():
    assert not role_allows("superhero", Action.VIEW_WORKSPACE)
    assert set(ROLE_PERMISSIONS) == set(Role)
