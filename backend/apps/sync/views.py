from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.exceptions import ErrorSerializer
from apps.storage.store import get_record_store
from apps.storage.views import StorageErrorMixin
from apps.tenancy.api import WorkspaceScopedAPIView
from apps.tenancy.permissions import Action

from .serializers import SyncBatchSerializer, SyncResponseSerializer
from .service import apply_batch


class SyncView(StorageErrorMixin, WorkspaceScopedAPIView):
    """Upload a batch of changes queued on a device while it was offline."""

    required_action = Action.EDIT_RECORDS

    @extend_schema(
        operation_id="sync_upload",
        request=SyncBatchSerializer,
        responses={
            200: SyncResponseSerializer,
            400: OpenApiResponse(ErrorSerializer),
            403: OpenApiResponse(ErrorSerializer),
            404: OpenApiResponse(ErrorSerializer),
        },
    )
    def post(self, request: Request, workspace_id: str) -> Response:
        body = SyncBatchSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        store = get_record_store(self.workspace_context.workspace)
        return Response(apply_batch(store, request.user, body.validated_data["operations"]))
