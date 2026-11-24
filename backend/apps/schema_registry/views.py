from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.exceptions import ErrorSerializer
from apps.tenancy.api import WorkspaceScopedAPIView
from apps.tenancy.permissions import Action

from . import registry
from .ssd import SSD


class NoActiveSchema(NotFound):
    default_detail = "This workspace doesn't have a published structure yet."
    default_code = "no_active_schema"


class ActiveSchemaView(WorkspaceScopedAPIView):
    """The workspace's active (published) schema as an SSD document. Read-only."""

    required_action = Action.VIEW_SCHEMA

    @extend_schema(
        operation_id="workspace_schema_retrieve",
        responses={200: SSD, 404: OpenApiResponse(ErrorSerializer)},
    )
    def get(self, request: Request, workspace_id: str) -> Response:
        version = registry.get_active_version(self.workspace_context.workspace)
        if version is None:
            raise NoActiveSchema()
        return Response(registry.to_document(version))
