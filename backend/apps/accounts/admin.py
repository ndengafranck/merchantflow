from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm

from apps.audit.services import record_event

from .models import DeviceInstallation, User
from .services import owned_workspace_names


class MerchantFlowUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"

    def clean_is_active(self) -> bool:
        is_active = self.cleaned_data["is_active"]
        if self.instance.pk and self.instance.is_active and not is_active:
            owned = owned_workspace_names(self.instance)
            if owned:
                raise forms.ValidationError(
                    "This person owns " + ", ".join(owned) + ". Transfer ownership "
                    "before deactivating the account, or the workspace has no owner."
                )
        return is_active


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = MerchantFlowUserChangeForm
    ordering = ["email"]
    list_display = ["email", "full_name", "is_active", "is_staff"]
    search_fields = ["email", "full_name", "phone"]
    readonly_fields = ["last_login", "date_joined"]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Profile", {"fields": ["full_name", "phone"]}),
        ("Access", {"fields": ["is_active", "is_staff", "is_superuser"]}),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [
        (None, {"fields": ["email", "full_name", "password1", "password2"]}),
    ]

    def save_model(self, request, obj, form, change) -> None:
        super().save_model(request, obj, form, change)
        changed = [f for f in form.changed_data if f != "password"]
        if change and changed:
            record_event(
                action="user.updated",
                target=obj,
                actor=request.user,
                metadata={
                    "channel": "admin",
                    "changes": {f: str(form.cleaned_data[f]) for f in changed},
                },
            )
        elif not change:
            record_event(
                action="user.created", target=obj, actor=request.user, metadata={"channel": "admin"}
            )

    def user_change_password(self, request, id, form_url=""):
        response = super().user_change_password(request, id, form_url)
        if request.method == "POST" and response.status_code == 302:
            user = User.objects.get(pk=id)
            record_event(
                action="user.password_set",
                target=user,
                actor=request.user,
                metadata={"channel": "admin"},
            )
        return response


@admin.register(DeviceInstallation)
class DeviceInstallationAdmin(admin.ModelAdmin):
    """Read-only: revoke through the API or services so sessions end too."""

    list_display = ["label", "user", "status", "last_login_at", "created_at"]
    list_filter = ["status"]
    search_fields = ["user__email", "label"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
