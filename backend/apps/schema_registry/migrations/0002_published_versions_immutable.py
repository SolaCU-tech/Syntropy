"""Make published schema versions immutable in the database itself.

The registry never edits a published version, but this trigger also stops admin edits, raw
SQL and future bugs. Allowed after publication: only status published -> superseded.
Deleting a published or superseded version is refused too.
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION schema_version_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'schema version % is % and cannot be deleted', OLD.id, OLD.status
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.status = 'draft' THEN
        RETURN NEW;
    END IF;

    IF NEW.content IS DISTINCT FROM OLD.content
        OR NEW.checksum IS DISTINCT FROM OLD.checksum
        OR NEW.spec_version IS DISTINCT FROM OLD.spec_version
        OR NEW.number IS DISTINCT FROM OLD.number
        OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
        OR NEW.based_on_id IS DISTINCT FROM OLD.based_on_id
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
    THEN
        RAISE EXCEPTION 'schema version % is % and its content is immutable', OLD.id, OLD.status
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status
        AND NOT (OLD.status = 'published' AND NEW.status = 'superseded')
    THEN
        RAISE EXCEPTION 'schema version % cannot go from % to %', OLD.id, OLD.status, NEW.status
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER schema_version_immutable
    BEFORE UPDATE OR DELETE ON schema_registry_schemaversion
    FOR EACH ROW EXECUTE FUNCTION schema_version_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS schema_version_immutable ON schema_registry_schemaversion;
DROP FUNCTION IF EXISTS schema_version_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("schema_registry", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
