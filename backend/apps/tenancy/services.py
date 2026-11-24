from django.db import transaction
from django.utils.text import slugify

from .models import Membership, Organization, Role, Workspace


@transaction.atomic
def create_workspace(user, name: str, organization_name: str | None = None) -> Workspace:
    """Create a workspace in a new organization, with ``user`` as its owner."""
    organization = Organization.objects.create(name=organization_name or name, created_by=user)
    slug = slugify(name)[:50] or "workspace"
    workspace = Workspace.objects.create(organization=organization, name=name, slug=slug)
    Membership.objects.create(user=user, workspace=workspace, role=Role.OWNER)
    return workspace
