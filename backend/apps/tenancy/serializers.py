from rest_framework import serializers

from .models import Role, Workspace


class WorkspaceSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    role = serializers.ChoiceField(choices=Role.choices, read_only=True)

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "slug",
            "status",
            "timezone",
            "currency",
            "organization_name",
            "role",
            "created_at",
        ]
        read_only_fields = fields


class WorkspaceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    organization_name = serializers.CharField(max_length=120, required=False)
