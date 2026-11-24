"""The registry: drafts, publication, supersession and immutable published snapshots."""

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction

from apps.schema_registry import registry
from apps.schema_registry.models import SchemaVersion
from apps.schema_registry.ssd import SSDValidationError
from apps.tenancy.models import Workspace
from apps.tenancy.services import create_workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def published(workspace, owner, retail):
    draft = registry.create_draft(workspace, retail, created_by=owner)
    return registry.publish(draft, published_by=owner)


def test_create_draft_stores_validated_content_without_envelope(workspace, owner, retail):
    draft = registry.create_draft(workspace, retail, created_by=owner)

    assert draft.number == 1
    assert draft.status == SchemaVersion.Status.DRAFT
    assert draft.spec_version == "1.0"
    assert draft.based_on is None
    assert set(draft.content) == {"tables", "relationships", "source_mappings"}
    assert len(draft.checksum) == 64


def test_invalid_document_never_becomes_a_draft(workspace, retail):
    retail["tables"] = []

    with pytest.raises(SSDValidationError):
        registry.create_draft(workspace, retail)

    assert not SchemaVersion.objects.exists()


def test_publish_makes_the_version_active(workspace, published):
    assert published.status == SchemaVersion.Status.PUBLISHED
    assert published.published_at is not None
    assert registry.get_active_version(workspace) == published

    entry = registry.get_registry_entry(workspace)
    assert entry.schema_version == published
    assert entry.storage_backend == "shared_jsonb"


def test_to_document_adds_the_envelope(workspace, published):
    doc = registry.to_document(published)

    assert doc["spec_version"] == "1.0"
    assert doc["workspace_id"] == str(workspace.id)
    assert doc["version"] == 1
    assert doc["status"] == "published"
    assert registry.to_ssd(published).table_by_key("sales") is not None


def test_publishing_a_new_version_supersedes_the_old_one(workspace, owner, published, retail):
    retail["tables"][0]["label"] = "Clients"
    draft = registry.create_draft(workspace, retail, created_by=owner)
    assert draft.number == 2
    assert draft.based_on == published

    registry.publish(draft)

    published.refresh_from_db()
    assert published.status == SchemaVersion.Status.SUPERSEDED
    assert registry.get_active_version(workspace) == draft
    assert SchemaVersion.objects.filter(workspace=workspace, status="published").count() == 1


def test_publishing_a_draft_built_on_an_old_version_fails(workspace, published, retail):
    first = registry.create_draft(workspace, retail)
    second = registry.create_draft(workspace, retail)
    registry.publish(first)

    with pytest.raises(registry.StaleBaseVersion):
        registry.publish(second)

    second.refresh_from_db()
    assert second.status == SchemaVersion.Status.DRAFT


def test_only_drafts_can_be_published(published):
    with pytest.raises(registry.NotADraft):
        registry.publish(published)


def test_machine_keys_never_change_between_versions(workspace, published, retail):
    retail["tables"][0]["fields"][0]["key"] = "full_name"
    draft = registry.create_draft(workspace, retail)

    with pytest.raises(registry.MachineKeyChanged):
        registry.publish(draft)

    assert registry.get_active_version(workspace) == published


def test_a_document_for_another_workspace_is_refused(workspace, owner, retail):
    other = create_workspace(owner, "Other shop")
    retail["workspace_id"] = str(other.id)

    with pytest.raises(registry.WrongWorkspace):
        registry.create_draft(workspace, retail)


def test_a_base_version_from_another_workspace_is_refused(workspace, owner, published, retail):
    other = create_workspace(owner, "Other shop")

    with pytest.raises(registry.WrongWorkspace):
        registry.create_draft(other, retail, based_on=published)


# Immutability is enforced by PostgreSQL itself, not just by the registry code.


def test_published_content_cannot_be_changed_even_with_update(published):
    with pytest.raises(IntegrityError, match="immutable"), transaction.atomic():
        SchemaVersion.objects.filter(pk=published.pk).update(content={"tables": []})


def test_published_content_cannot_be_changed_with_raw_sql(published):
    with (
        pytest.raises(IntegrityError, match="immutable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE schema_registry_schemaversion SET checksum = 'x' WHERE id = %s",
            [published.pk],
        )


def test_published_version_cannot_go_back_to_draft(published):
    with pytest.raises(IntegrityError, match="cannot go from"), transaction.atomic():
        SchemaVersion.objects.filter(pk=published.pk).update(status="draft")


def test_superseded_version_cannot_be_republished(workspace, published, retail):
    registry.publish(registry.create_draft(workspace, retail))

    with pytest.raises(IntegrityError), transaction.atomic():
        SchemaVersion.objects.filter(pk=published.pk).update(status="published")


def test_published_version_cannot_be_deleted(published):
    with pytest.raises(IntegrityError, match="cannot be deleted"), transaction.atomic():
        SchemaVersion.objects.filter(pk=published.pk).delete()


def test_drafts_can_still_be_edited_and_deleted(workspace, retail):
    draft = registry.create_draft(workspace, retail)

    SchemaVersion.objects.filter(pk=draft.pk).update(content={"tables": []})
    SchemaVersion.objects.filter(pk=draft.pk).delete()

    assert not SchemaVersion.objects.exists()


def test_tampered_draft_cannot_be_published(workspace, retail):
    draft = registry.create_draft(workspace, retail)
    SchemaVersion.objects.filter(pk=draft.pk).update(content={"tables": []})

    with pytest.raises(registry.RegistryError):
        registry.publish(draft)


def test_two_published_versions_are_impossible(workspace, published, retail):
    draft = registry.create_draft(workspace, retail)

    with pytest.raises(IntegrityError), transaction.atomic():
        SchemaVersion.objects.filter(pk=draft.pk).update(
            status="published", published_at=published.published_at
        )


# Seeding the hand-written retail example.


def test_seed_retail_example_publishes_the_retail_ssd(owner):
    call_command("seed_retail_example", owner.username)

    workspace = Workspace.objects.get(memberships__user=owner)
    version = registry.get_active_version(workspace)
    assert version.number == 1
    assert [t.key for t in registry.to_ssd(version).tables] == ["customers", "products", "sales"]


def test_seed_retail_example_is_idempotent(owner):
    call_command("seed_retail_example", owner.username)
    call_command("seed_retail_example", owner.username)

    assert Workspace.objects.filter(memberships__user=owner).count() == 1
    assert SchemaVersion.objects.count() == 1


def test_seed_retail_example_needs_an_existing_user(db):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="createsuperuser"):
        call_command("seed_retail_example", "nobody")


def test_export_ssd_schema_check_passes():
    call_command("export_ssd_schema", "--check")
