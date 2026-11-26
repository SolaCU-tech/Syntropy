from django.urls import path

from .views import RecordDetailView, RecordListView

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/tables/<str:table_id>/records/",
        RecordListView.as_view(),
        name="record-list",
    ),
    path(
        "workspaces/<uuid:workspace_id>/tables/<str:table_id>/records/<uuid:record_id>/",
        RecordDetailView.as_view(),
        name="record-detail",
    ),
]
