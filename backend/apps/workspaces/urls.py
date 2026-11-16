from django.urls import include, path

from . import views

workspace_scoped = [
    path("", views.WorkspaceDetailView.as_view(), name="workspace-detail"),
    path("members/", views.MemberListView.as_view(), name="member-list"),
    path("members/<uuid:membership_id>/", views.MemberDetailView.as_view(), name="member-detail"),
    path("", include("apps.devices.urls")),
]

urlpatterns = [
    path("", views.MyWorkspacesView.as_view(), name="my-workspaces"),
    path("current/", views.CurrentWorkspaceView.as_view(), name="current-workspace"),
    path("<uuid:workspace_id>/", include(workspace_scoped)),
]
