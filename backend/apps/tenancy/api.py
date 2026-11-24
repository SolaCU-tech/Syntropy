"""DRF building blocks for workspace-scoped endpoints."""

from typing import Any

from rest_framework.request import Request
from rest_framework.views import APIView

from .permissions import Action
from .resolver import WorkspaceContext, resolve_workspace


class WorkspaceScopedAPIView(APIView):
    """Base view for any endpoint under ``/api/workspaces/<workspace_id>/``.

    After authentication it runs the workspace resolver and checks ``required_action``, so a
    subclass can't forget either. The trusted context is on ``self.workspace_context`` (and
    ``request.workspace_context``); handlers never look the workspace up themselves.
    """

    required_action: Action = Action.VIEW_WORKSPACE
    workspace_context: WorkspaceContext

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)  # authentication and default permissions
        context = resolve_workspace(request.user, kwargs["workspace_id"])
        context.require(self.required_action)
        self.workspace_context = context
        request.workspace_context = context
