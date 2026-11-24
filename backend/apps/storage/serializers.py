from rest_framework import serializers

from apps.core.exceptions import ErrorSerializer

_VALUES_HELP = (
    'Values keyed by SSD field ID. Decimals are strings ("1500.00"), dates are '
    '"YYYY-MM-DD", datetimes are ISO 8601 in UTC, and a reference field holds the linked '
    "record's ID."
)


class RecordSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    table_id = serializers.CharField()
    version = serializers.IntegerField(help_text="Send this back when editing the record.")
    schema_version = serializers.IntegerField(
        help_text="The schema version the record was last written against."
    )
    values = serializers.DictField(
        child=serializers.JSONField(allow_null=True), help_text=_VALUES_HELP
    )
    created_by = serializers.IntegerField(source="created_by_id", allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class RecordCreateSerializer(serializers.Serializer):
    id = serializers.UUIDField(
        required=False,
        help_text="Optional client-generated ID (UUIDv7 from offline devices).",
    )
    values = serializers.DictField(
        child=serializers.JSONField(allow_null=True), help_text=_VALUES_HELP
    )


class RecordUpdateSerializer(serializers.Serializer):
    version = serializers.IntegerField(
        min_value=1, help_text="The version you last read. A stale version returns 409."
    )
    values = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        help_text=_VALUES_HELP + " Only the fields sent change; null clears a field.",
    )


class RecordDeleteQuerySerializer(serializers.Serializer):
    version = serializers.IntegerField(
        min_value=1, required=False, help_text="If sent, a stale version returns 409."
    )


class RecordConflictSerializer(ErrorSerializer):
    current = RecordSerializer(help_text="The record as it is now on the server.")


class RecordDeletedSerializer(serializers.Serializer):
    deleted = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="Every record removed, including any removed by a cascade.",
    )


class RecordPageSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True, help_text="The next page, or null.")
    previous = serializers.URLField(allow_null=True, help_text="The previous page, or null.")
    results = RecordSerializer(many=True)
