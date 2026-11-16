from django.contrib.admin.apps import AdminConfig


class MerchantFlowAdminConfig(AdminConfig):
    """``django.contrib.admin`` with the protected site (``admin_site.py``)."""

    default_site = "apps.common.admin_site.MerchantFlowAdminSite"
