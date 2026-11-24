"""Database-side type and required-field checks for JSONB records (ADR-08, agreed 24 Nov 2026).

The app validates every write (``apps/storage/values.py``). This migration makes the database
refuse the same bad values even if the app is bypassed or has a bug:

* When a schema version is published, a trigger on ``schema_registry_schemaversion`` compiles
  each table's field rules into ``storage_field_rules`` (the FieldRules model, migration
  0003). Published versions are immutable, so the rules never go stale, and nothing in Python
  has to remember to compile them.
* A trigger on ``business_records`` checks every insert, and every update that changes the
  data or the schema version, against the rules of the record's schema version: no unknown
  fields, required fields present, and each value in its canonical form (see values.py):
  integers are JSON numbers within +/-(2^53 - 1), decimals are strings with exactly the
  field's scale, dates are YYYY-MM-DD, datetimes are UTC ending in Z, enums are an option key,
  text is within its length limit, and numbers are within min/max.

Reference fields aren't in the JSONB (links live in record_relationships), so they have no
rule here; their required-ness is checked by the store.
"""

from django.db import migrations

FORWARD = r"""
CREATE FUNCTION storage_compile_field_rules(version_id uuid, content jsonb) RETURNS void AS $$
    INSERT INTO storage_field_rules (schema_version_id, table_id, allowed, fields)
    SELECT version_id,
           t.value ->> 'id',
           coalesce(jsonb_object_agg(f.value ->> 'id', true)
                    FILTER (WHERE f.value ->> 'type' <> 'reference'), '{}'),
           coalesce(jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
               'id', f.value ->> 'id',
               'type', f.value ->> 'type',
               'required', coalesce((f.value ->> 'required')::boolean, false),
               'options', CASE WHEN jsonb_typeof(f.value -> 'options') = 'array' THEN
                              (SELECT jsonb_object_agg(o.value ->> 'key', true)
                               FROM jsonb_array_elements(f.value -> 'options') AS o)
                          END,
               'max_length', coalesce((f.value ->> 'max_length')::int,
                                      CASE WHEN f.value ->> 'type' = 'text' THEN 10000 END),
               'min', f.value ->> 'min_value',
               'max', f.value ->> 'max_value',
               'scale', CASE WHEN f.value ->> 'type' = 'decimal'
                             THEN coalesce((f.value ->> 'scale')::int, 0) END,
               'precision', CASE WHEN f.value ->> 'type' = 'decimal'
                                 THEN coalesce((f.value ->> 'precision')::int, 28) END
           ))) FILTER (WHERE f.value ->> 'type' <> 'reference'), '[]')
    FROM jsonb_array_elements(content -> 'tables') AS t,
         jsonb_array_elements(t.value -> 'fields') AS f
    GROUP BY t.value ->> 'id'
    ON CONFLICT DO NOTHING;
$$ LANGUAGE sql;

CREATE FUNCTION storage_compile_on_publish() RETURNS trigger AS $$
BEGIN
    PERFORM storage_compile_field_rules(NEW.id, NEW.content);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER schema_version_compile_field_rules
    AFTER INSERT OR UPDATE OF status ON schema_registry_schemaversion
    FOR EACH ROW WHEN (NEW.status = 'published')
    EXECUTE FUNCTION storage_compile_on_publish();
"""

FORWARD += r"""
-- Versions published before this migration.
SELECT storage_compile_field_rules(id, content)
FROM schema_registry_schemaversion WHERE status <> 'draft';

CREATE FUNCTION business_record_check_values() RETURNS trigger AS $$
DECLARE
    rules record;
    rule jsonb;
    value jsonb;
    kind text;
    s text;
    n numeric;
    bad text;
BEGIN
    SELECT allowed, fields INTO rules FROM storage_field_rules
    WHERE schema_version_id = NEW.schema_version_id AND table_id = NEW.table_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'record %: table % is not in published schema version %',
            NEW.id, NEW.table_id, NEW.schema_version_id
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT k INTO bad FROM jsonb_object_keys(NEW.data) AS k WHERE NOT rules.allowed ? k LIMIT 1;
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'record %: % is not a field of table %', NEW.id, bad, NEW.table_id
            USING ERRCODE = 'check_violation';
    END IF;

    FOR rule IN SELECT * FROM jsonb_array_elements(rules.fields) LOOP
        value := NEW.data -> (rule ->> 'id');
        IF value IS NULL OR jsonb_typeof(value) = 'null' THEN
            IF (rule ->> 'required')::boolean THEN
                RAISE EXCEPTION 'record %: % is required', NEW.id, rule ->> 'id'
                    USING ERRCODE = 'check_violation';
            END IF;
            CONTINUE;
        END IF;

        kind := rule ->> 'type';
        bad := NULL;
        n := NULL;
        IF kind = 'integer' THEN
            IF jsonb_typeof(value) <> 'number' THEN
                bad := 'must be a whole number';
            ELSE
                n := value::text::numeric;
                IF n <> trunc(n) OR abs(n) > 9007199254740991 THEN
                    bad := 'must be a whole number within +/-(2^53 - 1)';
                END IF;
            END IF;
        ELSIF kind = 'boolean' THEN
            IF jsonb_typeof(value) <> 'boolean' THEN bad := 'must be true or false'; END IF;
        ELSIF jsonb_typeof(value) <> 'string' THEN
            bad := 'must be a string';
        ELSE
            s := value #>> '{}';
            IF kind = 'text' THEN
                IF (rule ->> 'required')::boolean AND btrim(s) = '' THEN
                    bad := 'is required';
                ELSIF char_length(s) > (rule ->> 'max_length')::int THEN
                    bad := 'is too long';
                END IF;
            ELSIF kind = 'decimal' THEN
                IF (rule ->> 'scale')::int = 0 AND s !~ '^-?[0-9]+$'
                    OR (rule ->> 'scale')::int > 0
                       AND s !~ ('^-?[0-9]+\.[0-9]{' || (rule ->> 'scale') || '}$')
                THEN
                    bad := 'must be a decimal string with exactly ' || (rule ->> 'scale')
                           || ' decimal places';
                ELSE
                    n := s::numeric;
                    IF length(replace(ltrim(replace(s, '-', ''), '0'), '.', ''))
                       > (rule ->> 'precision')::int
                    THEN
                        bad := 'has too many digits';
                    END IF;
                END IF;
            ELSIF kind = 'date' THEN
                IF s !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' OR to_char(s::date, 'YYYY-MM-DD') <> s THEN
                    bad := 'must be a date written YYYY-MM-DD';
                END IF;
            ELSIF kind = 'datetime' THEN
                IF s !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$' THEN
                    bad := 'must be a UTC date and time ending in Z';
                ELSE
                    PERFORM s::timestamptz;
                END IF;
            ELSIF kind = 'enum' THEN
                IF NOT (rule -> 'options') ? s THEN bad := 'is not one of the options'; END IF;
            END IF;
        END IF;

        IF bad IS NULL AND n IS NOT NULL THEN
            IF rule ? 'min' AND n < (rule ->> 'min')::numeric THEN
                bad := 'is below the minimum ' || (rule ->> 'min');
            ELSIF rule ? 'max' AND n > (rule ->> 'max')::numeric THEN
                bad := 'is above the maximum ' || (rule ->> 'max');
            END IF;
        END IF;

        IF bad IS NOT NULL THEN
            RAISE EXCEPTION 'record %: % %', NEW.id, rule ->> 'id', bad
                USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;
    RETURN NEW;
EXCEPTION
    -- An unparseable date or datetime (e.g. 2026-02-30) is a bad value, not a crash.
    WHEN datetime_field_overflow OR invalid_datetime_format THEN
        RAISE EXCEPTION 'record %: % is not a real date or time', NEW.id, rule ->> 'id'
            USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER business_record_values_valid
    BEFORE INSERT OR UPDATE OF data, schema_version_id ON business_records
    FOR EACH ROW EXECUTE FUNCTION business_record_check_values();
"""

REVERSE = """
DROP TRIGGER IF EXISTS business_record_values_valid ON business_records;
DROP FUNCTION IF EXISTS business_record_check_values();
DROP TRIGGER IF EXISTS schema_version_compile_field_rules ON schema_registry_schemaversion;
DROP FUNCTION IF EXISTS storage_compile_on_publish();
DROP FUNCTION IF EXISTS storage_compile_field_rules(uuid, jsonb);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("storage", "0003_field_rules"),
        ("schema_registry", "0002_published_versions_immutable"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
