"""Database-side safeguards Django can't declare (spec section 9, integrity requirements).

* Composite foreign keys on (workspace_id, table_id, record_id), so a link or a unique value
  can't cross workspaces or point at a record in the wrong table.
* Deleting a record that something links to is refused (RESTRICT) unless the store already
  applied the relationship's delete policy. A link's own source record takes it with it.
* A record's id, workspace and table are immutable.
* Record data must be a flat JSON object of scalars whose keys are field IDs (fld_...).
"""

from django.db import migrations

FORWARD = """
ALTER TABLE record_relationships
    ADD CONSTRAINT record_link_from_record
        FOREIGN KEY (workspace_id, from_table_id, from_record_id)
        REFERENCES business_records (workspace_id, table_id, id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    ADD CONSTRAINT record_link_to_record
        FOREIGN KEY (workspace_id, to_table_id, to_record_id)
        REFERENCES business_records (workspace_id, table_id, id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT record_link_relationship_id_format
        CHECK (relationship_id ~ '^rel_[a-z0-9_]{3,48}$');

ALTER TABLE unique_values
    ADD CONSTRAINT unique_value_record
        FOREIGN KEY (workspace_id, table_id, record_id)
        REFERENCES business_records (workspace_id, table_id, id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    ADD CONSTRAINT unique_value_field_id_format
        CHECK (field_id ~ '^fld_[a-z0-9_]{3,48}$');

-- jsonpath with no regular expression: about 10x cheaper per row than jsonb_each + regex.
ALTER TABLE business_records
    ADD CONSTRAINT business_record_data_valid CHECK (
        jsonb_typeof(data) = 'object'
        AND NOT jsonb_path_exists(
            data,
            '$.keyvalue() ? (!(@.key starts with "fld_")
                             || @.value.type() == "object" || @.value.type() == "array")'
        )
    );

CREATE FUNCTION business_record_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
        OR NEW.table_id IS DISTINCT FROM OLD.table_id
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'business record % cannot change its id, workspace, table or creation time', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <= OLD.version THEN
        RAISE EXCEPTION 'business record % version must increase on every change', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER business_record_immutable_identity
    BEFORE UPDATE ON business_records
    FOR EACH ROW EXECUTE FUNCTION business_record_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS business_record_immutable_identity ON business_records;
DROP FUNCTION IF EXISTS business_record_guard();
ALTER TABLE business_records DROP CONSTRAINT IF EXISTS business_record_data_valid;
ALTER TABLE unique_values
    DROP CONSTRAINT IF EXISTS unique_value_record,
    DROP CONSTRAINT IF EXISTS unique_value_field_id_format;
ALTER TABLE record_relationships
    DROP CONSTRAINT IF EXISTS record_link_from_record,
    DROP CONSTRAINT IF EXISTS record_link_to_record,
    DROP CONSTRAINT IF EXISTS record_link_relationship_id_format;
"""


class Migration(migrations.Migration):
    dependencies = [("storage", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
