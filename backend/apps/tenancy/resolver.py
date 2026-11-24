"""The workspace resolver: the tenant-isolation checkpoint (spec section 6).

Every request that touches a workspace's data passes through ``resolve_workspace`` before
anything else. The workspace ID in a URL is only a lookup; access comes from a membership
row checked on the server, never from anything the client sends.
"""

from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from rest_framework.exceptions import NotFound, PermissionDenied

from .models import Membership, Workspace
from .permissions import Action, role_allows


class WorkspaceNotFound(NotFound):
    # One answer for "doesn't exist" and "not yours", so IDs of other businesses' workspaces
    # can't be discovered by probing.
    default_detail = "We couldn't find that workspace."
    default_code = "workspace_not_found"


class WorkspacePermissionDenied(PermissionDenied):
    default_detail = "Your role in this workspace doesn't allow that."
    default_code = "workspace_permission_denied"


@dataclass(frozen=True)
class WorkspaceContext:
    """The trusted workspace context for one request."""

    workspace: Workspace
    membership: Membership

    @property
    def role(self) -> str:
        return self.membership.role

    def can(self, action: Action) -> bool:
        return role_allows(self.role, action)

    def require(self, action: Action) -> None:
        if not self.can(action):
            raise WorkspacePermissionDenied()


def resolve_workspace(
    user: AbstractBaseUser | AnonymousUser, workspace_id: UUID | str
) -> WorkspaceContext:
    """Return the context for ``user`` in ``workspace_id`` or raise WorkspaceNotFound."""
    if not (user and user.is_authenticated and user.is_active):
        raise WorkspaceNotFound()
    try:
        workspace_uuid = UUID(str(workspace_id))
    except ValueError:
        raise WorkspaceNotFound() from None
    membership = (
        Membership.objects.select_related("workspace", "workspace__organization")
        .filter(user=user, workspace_id=workspace_uuid)
        .exclude(workspace__status=Workspace.Status.ARCHIVED)
        .first()
    )
    if membership is None:
        raise WorkspaceNotFound()
    return WorkspaceContext(workspace=membership.workspace, membership=membership)
