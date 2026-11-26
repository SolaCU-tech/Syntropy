from rest_framework import serializers

from apps.storage.serializers import RecordSerializer

MAX_BATCH = 100


class SyncOperationSerializer(serializers.Serializer):
    idempotency_key = serializers.UUIDField(
        help_text="Generated once on the device when the change is queued; reused on retries."
    )
    op = serializers.ChoiceField(
        choices=["create", "update"],
        help_text="Deletes always need a connection, so they are never queued.",
    )
    table_id = serializers.RegexField(r"^tbl_[a-z0-9_]{3,48}$")
    record_id = serializers.UUIDField(
        help_text="For a create, the client-generated ID (UUIDv7) the device already uses."
    )
    base_version = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text="For an update: the record version the change was based on.",
    )
    schema_version = serializers.IntegerField(
        min_value=1, help_text="The schema version the form was validated against."
    )
    values = serializers.DictField(child=serializers.JSONField(allow_null=True))

    def validate(self, attrs):
        if attrs["op"] == "update" and "base_version" not in attrs:
            raise serializers.ValidationError({"base_version": "An edit needs base_version."})
        if attrs["op"] == "create":
            attrs.pop("base_version", None)
        return attrs


class SyncBatchSerializer(serializers.Serializer):
    operations = SyncOperationSerializer(many=True, max_length=MAX_BATCH, min_length=1)

    def validate_operations(self, value):
        keys = [op["idempotency_key"] for op in value]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("Each operation needs its own idempotency_key.")
        return value


class SyncErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()), required=False
    )


class SyncResultSerializer(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["applied", "conflict", "rejected", "schema_changed"])
    replayed = serializers.BooleanField(
        help_text="True when this key was seen before and the stored outcome is returned."
    )
    record = RecordSerializer(required=False, help_text="The saved record (applied).")
    current = RecordSerializer(
        required=False, help_text="The record as it is now on the server (conflict)."
    )
    error = SyncErrorSerializer(required=False)


class SyncResponseSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField(help_text="The workspace's active schema version.")
    results = SyncResultSerializer(many=True)
