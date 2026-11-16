from django.contrib import admin

from .models import Workspace, WorkspaceMembership


class NoDeleteAdmin(admin.ModelAdmin):
    """History is archived through status fields, never deleted."""

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Workspace)
class WorkspaceAdmin(NoDeleteAdmin):
    list_display = ["name", "slug", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["name", "slug"]
    readonly_fields = ["slug", "created_at", "updated_at"]

    def has_add_permission(self, request) -> bool:
        # A workspace needs an owner membership: use `manage.py create_workspace`.
        return False


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(NoDeleteAdmin):
    list_display = ["user", "workspace", "role", "status"]
    list_filter = ["role", "status"]
    search_fields = ["user__email", "workspace__name"]
    autocomplete_fields = ["user", "workspace"]
