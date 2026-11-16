from django.contrib import admin

from apps.audit.services import record_event

from .models import Workspace, WorkspaceDevice, WorkspaceMembership


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

    def save_model(self, request, obj, form, change) -> None:
        super().save_model(request, obj, form, change)
        if change and form.changed_data:
            record_event(
                action="workspace.updated",
                target=obj,
                actor=request.user,
                workspace=obj,
                metadata={
                    "channel": "admin",
                    "changes": {f: str(form.cleaned_data[f]) for f in form.changed_data},
                },
            )


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(NoDeleteAdmin):
    """View only. Roles, statuses and ownership change through the services,
    which enforce the ownership rules and write the audit trail."""

    list_display = ["user", "workspace", "role", "status"]
    list_filter = ["role", "status"]
    search_fields = ["user__email", "workspace__name"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(WorkspaceDevice)
class WorkspaceDeviceAdmin(NoDeleteAdmin):
    """Read-only: revoke through the API so the change is audited."""

    list_display = ["installation", "workspace", "status", "last_seen_at"]
    list_filter = ["status"]
    search_fields = ["installation__user__email", "workspace__name"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
