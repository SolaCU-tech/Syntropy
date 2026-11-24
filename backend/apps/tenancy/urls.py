from django.urls import path

from apps.schema_registry.views import ActiveSchemaView

from .views import WorkspaceDetailView, WorkspaceListView

urlpatterns = [
    path("workspaces/", WorkspaceListView.as_view(), name="workspace-list"),
    path("workspaces/<uuid:workspace_id>/", WorkspaceDetailView.as_view(), name="workspace-detail"),
    path(
        "workspaces/<uuid:workspace_id>/schema/",
        ActiveSchemaView.as_view(),
        name="workspace-schema",
    ),
]
