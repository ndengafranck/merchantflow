from django.contrib import admin

from .models import Device


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "workspace", "status", "last_seen_at"]
    list_filter = ["status"]
    search_fields = ["name", "user__email", "workspace__name"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False  # revoke through the API so the change is audited

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
