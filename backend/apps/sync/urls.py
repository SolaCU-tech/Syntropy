from django.urls import path

from .views import SyncView

urlpatterns = [
    path("workspaces/<uuid:workspace_id>/sync/", SyncView.as_view(), name="workspace-sync"),
]
