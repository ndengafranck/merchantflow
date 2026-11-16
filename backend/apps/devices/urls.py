from django.urls import path

from . import views

# Included under /workspaces/<workspace_id>/ by apps.workspaces.urls.
urlpatterns = [
    path("devices/", views.DeviceListView.as_view(), name="device-list"),
    path(
        "devices/<uuid:device_id>/revoke/", views.DeviceRevokeView.as_view(), name="device-revoke"
    ),
    path("sync/handshake/", views.SyncHandshakeView.as_view(), name="sync-handshake"),
]
