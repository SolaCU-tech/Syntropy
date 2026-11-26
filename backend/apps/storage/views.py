"""Record endpoints: browse, create, read, edit and delete records of one logical table.

Every request goes through the workspace resolver (WorkspaceScopedAPIView) and then the
record store, which is bound to the resolved workspace. Paths follow spec section 11.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.exceptions import ErrorSerializer
from apps.tenancy.api import WorkspaceScopedAPIView
from apps.tenancy.permissions import Action
from apps.tenancy.resolver import WorkspacePermissionDenied

from . import errors
from .serializers import (
    RecordConflictSerializer,
    RecordCreateSerializer,
    RecordDeletedSerializer,
    RecordDeleteQuerySerializer,
    RecordPageSerializer,
    RecordSerializer,
    RecordUpdateSerializer,
)
from .store import JsonbRecordStore, get_record_store

_STATUS = {
    errors.NoActiveSchema: status.HTTP_404_NOT_FOUND,
    errors.UnknownTable: status.HTTP_404_NOT_FOUND,
    errors.RecordNotFound: status.HTTP_404_NOT_FOUND,
    errors.RecordValidationError: status.HTTP_400_BAD_REQUEST,
    errors.ImportValidationError: status.HTTP_400_BAD_REQUEST,
    errors.InvalidReference: status.HTTP_400_BAD_REQUEST,
    errors.DuplicateValue: status.HTTP_409_CONFLICT,
    errors.RecordExists: status.HTTP_409_CONFLICT,
    errors.RecordInUse: status.HTTP_409_CONFLICT,
    errors.VersionConflict: status.HTTP_409_CONFLICT,
}

_ERROR = OpenApiResponse(ErrorSerializer)


class RecordPagination(CursorPagination):
    ordering = ("-created_at", "-id")
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class _RecordView(WorkspaceScopedAPIView):
    _actions = {
        "GET": Action.VIEW_WORKSPACE,
        "POST": Action.EDIT_RECORDS,
        "PATCH": Action.EDIT_RECORDS,
        # Delete permission depends on who created the record; checked in the handler.
        "DELETE": Action.VIEW_WORKSPACE,
    }

    @property
    def required_action(self) -> Action:  # type: ignore[override]
        return self._actions.get(self.request.method, Action.VIEW_WORKSPACE)

    @property
    def store(self) -> JsonbRecordStore:
        return get_record_store(self.workspace_context.workspace)

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, errors.StorageError):
            body = {"code": exc.code, "message": exc.message}
            if exc.details:
                body["details"] = exc.details
            if isinstance(exc, errors.VersionConflict):
                body["current"] = RecordSerializer(exc.current).data
            return Response(body, status=_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST))
        return super().handle_exception(exc)


class RecordListView(_RecordView):
    """Browse a table's records (newest first) and create new ones."""

    @extend_schema(
        operation_id="records_list",
        parameters=[
            OpenApiParameter("cursor", str, description="From the previous page's next link."),
            OpenApiParameter("page_size", int, description="Up to 200; default 50."),
        ],
        responses={200: RecordPageSerializer, 404: _ERROR},
    )
    def get(self, request: Request, workspace_id: str, table_id: str) -> Response:
        store = self.store
        paginator = RecordPagination()
        page = paginator.paginate_queryset(store.queryset(table_id), request, view=self)
        records = store.hydrate(table_id, page)
        return paginator.get_paginated_response(RecordSerializer(records, many=True).data)

    @extend_schema(
        operation_id="records_create",
        request=RecordCreateSerializer,
        responses={201: RecordSerializer, 400: _ERROR, 404: _ERROR, 409: _ERROR},
    )
    def post(self, request: Request, workspace_id: str, table_id: str) -> Response:
        body = RecordCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        record = self.store.create(
            table_id,
            body.validated_data["values"],
            record_id=body.validated_data.get("id"),
            actor=request.user,
        )
        return Response(RecordSerializer(record).data, status=status.HTTP_201_CREATED)


class RecordDetailView(_RecordView):
    """Read, edit or delete one record."""

    @extend_schema(operation_id="records_retrieve", responses={200: RecordSerializer, 404: _ERROR})
    def get(self, request: Request, workspace_id: str, table_id: str, record_id) -> Response:
        return Response(RecordSerializer(self.store.get(table_id, record_id)).data)

    @extend_schema(
        operation_id="records_partial_update",
        request=RecordUpdateSerializer,
        responses={
            200: RecordSerializer,
            400: _ERROR,
            404: _ERROR,
            409: OpenApiResponse(
                RecordConflictSerializer,
                description="Stale version (with the current record) or a duplicate value.",
            ),
        },
    )
    def patch(self, request: Request, workspace_id: str, table_id: str, record_id) -> Response:
        body = RecordUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        record = self.store.update(
            table_id,
            record_id,
            body.validated_data["values"],
            expected_version=body.validated_data["version"],
            actor=request.user,
        )
        return Response(RecordSerializer(record).data)

    @extend_schema(
        operation_id="records_destroy",
        parameters=[RecordDeleteQuerySerializer],
        responses={200: RecordDeletedSerializer, 403: _ERROR, 404: _ERROR, 409: _ERROR},
    )
    def delete(self, request: Request, workspace_id: str, table_id: str, record_id) -> Response:
        query = RecordDeleteQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        store = self.store
        context = self.workspace_context
        if not context.can(Action.DELETE_ANY_RECORD):
            record = store.get(table_id, record_id)
            own = record.created_by_id == request.user.pk
            if not (own and context.can(Action.DELETE_OWN_RECORDS)):
                raise WorkspacePermissionDenied()
        deleted = store.delete(
            table_id,
            record_id,
            expected_version=query.validated_data.get("version"),
            actor=request.user,
        )
        return Response({"deleted": [str(d) for d in deleted]})
