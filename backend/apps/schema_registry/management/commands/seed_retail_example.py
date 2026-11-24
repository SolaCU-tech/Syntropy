from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.schema_registry import registry
from apps.schema_registry.examples import load_retail_ssd
from apps.tenancy.models import Membership, Role, Workspace
from apps.tenancy.services import create_workspace

WORKSPACE_NAME = "Ade's Provisions (example)"


class Command(BaseCommand):
    help = (
        "Create an example retail workspace (Customers, Products, Sales) owned by an existing "
        "user, and publish the hand-written retail SSD as its first schema version."
    )

    def add_arguments(self, parser):
        parser.add_argument("username", help="Existing user who will own the workspace")

    @transaction.atomic
    def handle(self, *args, username: str, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(
                f"No user '{username}'. Create one first: python manage.py createsuperuser"
            ) from None

        membership = (
            Membership.objects.filter(user=user, role=Role.OWNER, workspace__name=WORKSPACE_NAME)
            .select_related("workspace")
            .first()
        )
        workspace: Workspace = (
            membership.workspace if membership else create_workspace(user, WORKSPACE_NAME)
        )

        if registry.get_active_version(workspace) is not None:
            self.stdout.write(f"'{workspace.name}' already has a published schema; nothing to do.")
            return

        draft = registry.create_draft(workspace, load_retail_ssd(), created_by=user)
        version = registry.publish(draft, published_by=user)
        self.stdout.write(
            self.style.SUCCESS(
                f"Published retail schema v{version.number} for '{workspace.name}' "
                f"(workspace id {workspace.id})."
            )
        )
