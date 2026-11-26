from django.urls import path

from .views import LookupView, RecordDetailView, RecordListView, TableSummaryView

urlpatterns = [
    path("workspaces/<uuid:workspace_id>/tables/", TableSummaryView.as_view(), name="table-list"),
    path(
        "workspaces/<uuid:workspace_id>/tables/<str:table_id>/lookup/",
        LookupView.as_view(),
        name="record-lookup",
    ),
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
