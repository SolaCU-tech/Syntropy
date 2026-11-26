"""Record endpoints: browse, create, read, edit and delete records of one logical table.

Every request goes through the workspace resolver (WorkspaceScopedAPIView) and then the
record store, which is bound to the resolved workspace. Paths follow spec section 11.
"""

from django.db.models import Count, Max
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.exceptions import ErrorSerializer
from apps.tenancy.api import WorkspaceScopedAPIView
from apps.tenancy.permissions import Action
from apps.tenancy.resolver import WorkspacePermissionDenied

from . import errors
from .filters import (
    FilterError,
    apply_filters,
    apply_ordering,
    apply_search,
    parse_filter_param,
)
from .models import BusinessRecord
from .serializers import (
    LookupItemSerializer,
    RecordConflictSerializer,
    RecordCreateSerializer,
    RecordDeletedSerializer,
    RecordDeleteQuerySerializer,
    RecordPageSerializer,
    RecordSerializer,
    RecordUpdateSerializer,
    TableSummarySerializer,
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


class RecordPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class StorageErrorMixin:
    """Turns record-store errors into the standard error shape with the right status."""

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, FilterError):
            body = {
                "code": "invalid_filter",
                "message": "That filter can't be used.",
                "details": exc.details,
            }
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, errors.StorageError):
            body = {"code": exc.code, "message": exc.message}
            if exc.details:
                body["details"] = exc.details
            if isinstance(exc, errors.VersionConflict):
                body["current"] = RecordSerializer(exc.current).data
            return Response(body, status=_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST))
        return super().handle_exception(exc)  # type: ignore[misc]


class _RecordView(StorageErrorMixin, WorkspaceScopedAPIView):
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


class RecordListView(_RecordView):
    """Browse a table's records (newest first unless sorted) and create new ones."""

    @extend_schema(
        operation_id="records_list",
        parameters=[
            OpenApiParameter("page", int, description="Page number, from 1."),
            OpenApiParameter("page_size", int, description="Up to 200; default 50."),
            OpenApiParameter(
                "filter",
                str,
                description='JSON filter tree: {"all": [{"field": "fld_x", "op": "gte", '
                '"value": "1000"}]}. Operators depend on the field type.',
            ),
            OpenApiParameter("search", str, description="Text to find in the text fields."),
            OpenApiParameter(
                "ordering",
                str,
                description="A field ID, created_at or updated_at; prefix - for descending.",
            ),
        ],
        responses={200: RecordPageSerializer, 400: _ERROR, 404: _ERROR},
    )
    def get(self, request: Request, workspace_id: str, table_id: str) -> Response:
        store = self.store
        table = store.schema.table(table_id)
        qs = store.queryset(table_id)
        qs = apply_filters(
            store.schema, table, qs, parse_filter_param(request.query_params.get("filter"))
        )
        qs = apply_search(table, qs, request.query_params.get("search"))
        qs = apply_ordering(table, qs, request.query_params.get("ordering"))
        paginator = RecordPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
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


class TableSummaryView(StorageErrorMixin, WorkspaceScopedAPIView):
    """Record count and last change for every table in the active schema (Tables index)."""

    @extend_schema(operation_id="tables_list", responses={200: TableSummarySerializer(many=True)})
    def get(self, request: Request, workspace_id: str) -> Response:
        store = get_record_store(self.workspace_context.workspace)
        stats = {
            row["table_id"]: row
            for row in BusinessRecord.objects.filter(workspace=store.workspace)
            .values("table_id")
            .annotate(record_count=Count("id"), last_updated=Max("updated_at"))
        }
        body = [
            {
                "table_id": t.id,
                "record_count": stats.get(t.id, {}).get("record_count", 0),
                "last_updated": stats.get(t.id, {}).get("last_updated"),
            }
            for t in store.schema.ssd.tables
        ]
        return Response(TableSummarySerializer(body, many=True).data)


MAX_LOOKUP = 5000


class LookupView(StorageErrorMixin, WorkspaceScopedAPIView):
    """IDs and titles of a table's records, for link pickers and the offline cache."""

    @extend_schema(
        operation_id="records_lookup",
        parameters=[
            OpenApiParameter("search", str, description="Text to find in the text fields."),
            OpenApiParameter("limit", int, description=f"Up to {MAX_LOOKUP}; default 50."),
        ],
        responses={200: LookupItemSerializer(many=True), 404: _ERROR},
    )
    def get(self, request: Request, workspace_id: str, table_id: str) -> Response:
        store = get_record_store(self.workspace_context.workspace)
        table = store.schema.table(table_id)
        try:
            limit = int(request.query_params.get("limit", 50))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, MAX_LOOKUP))
        title = next((f.id for f in table.fields if f.display_role == "title"), None)
        qs = apply_search(table, store.queryset(table_id), request.query_params.get("search"))
        qs = apply_ordering(table, qs, title)
        rows = qs.values("id", "data", "version")[:limit]
        body = [
            {
                "id": r["id"],
                "title": r["data"].get(title) if title else None,
                "version": r["version"],
            }
            for r in rows
        ]
        return Response(LookupItemSerializer(body, many=True).data)
