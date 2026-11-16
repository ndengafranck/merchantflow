"""The Django admin site, with the same sign-in protection as the API."""

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse

from apps.accounts.login_protection import (
    begin_attempt,
    blocked_message,
    recognised_installation,
)
from apps.accounts.models import normalize_email
from apps.common.net import address_bucket, client_ip


class MerchantFlowAdminSite(admin.AdminSite):
    site_header = "MerchantFlow administration"
    site_title = "MerchantFlow admin"

    def login(self, request, extra_context=None):
        if request.method != "POST":
            return super().login(request, extra_context)
        identifier = normalize_email(request.POST.get("username", ""))
        attempt = begin_attempt(
            identifier=identifier,
            address=address_bucket(client_ip(request)),
            installation_id=recognised_installation(
                identifier, request.COOKIES.get(settings.DEVICE_COOKIE_NAME)
            ),
        )
        if attempt.blocked:
            response = HttpResponse(
                blocked_message(attempt.retry_after), status=429, content_type="text/plain"
            )
            response["Retry-After"] = str(attempt.retry_after)
            return response
        response = super().login(request, extra_context)
        signed_in = response.status_code == 302 and request.user.is_authenticated
        if signed_in:
            attempt.succeeded()
        else:
            attempt.failed()
        return response
