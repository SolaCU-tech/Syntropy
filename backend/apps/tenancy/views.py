from django.db.models import F
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .api import WorkspaceScopedAPIView
from .models import Workspace
from .serializers import WorkspaceCreateSerializer, WorkspaceSerializer
from .services import create_workspace


class WorkspaceListView(APIView):
    """The workspaces the signed-in user belongs to, and creating a new one."""

    @extend_schema(operation_id="workspaces_list", responses=WorkspaceSerializer(many=True))
    def get(self, request: Request) -> Response:
        workspaces = (
            Workspace.objects.filter(memberships__user=request.user)
            .exclude(status=Workspace.Status.ARCHIVED)
            .select_related("organization")
            .annotate(role=F("memberships__role"))
        )
        return Response(WorkspaceSerializer(workspaces, many=True).data)

    @extend_schema(
        operation_id="workspaces_create",
        request=WorkspaceCreateSerializer,
        responses={201: WorkspaceSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = WorkspaceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = create_workspace(request.user, **serializer.validated_data)
        workspace.role = "owner"
        return Response(WorkspaceSerializer(workspace).data, status=status.HTTP_201_CREATED)


class WorkspaceDetailView(WorkspaceScopedAPIView):
    """One workspace the signed-in user belongs to, with their role in it."""

    @extend_schema(operation_id="workspaces_retrieve", responses=WorkspaceSerializer)
    def get(self, request: Request, workspace_id: str) -> Response:
        workspace = self.workspace_context.workspace
        workspace.role = self.workspace_context.role
        return Response(WorkspaceSerializer(workspace).data)
