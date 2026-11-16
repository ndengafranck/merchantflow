from django.urls import path

from . import views

urlpatterns = [
    path("csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="auth-me"),
    path("installations/", views.InstallationListView.as_view(), name="installation-list"),
    path(
        "installations/<uuid:installation_id>/revoke/",
        views.InstallationRevokeView.as_view(),
        name="installation-revoke",
    ),
]
