"""Session engine (``SESSION_ENGINE``) backed by ``accounts.UserSession``."""

from django.contrib.auth import SESSION_KEY as AUTH_USER_SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore as DatabaseSessionStore

INSTALLATION_SESSION_KEY = "installation_id"


class SessionStore(DatabaseSessionStore):
    @classmethod
    def get_model_class(cls):
        from .models import UserSession

        return UserSession

    def create_model_instance(self, data: dict):
        """Copy the user and installation out of the payload into real columns."""
        instance = super().create_model_instance(data)
        instance.user_id = data.get(AUTH_USER_SESSION_KEY)
        instance.installation_id = data.get(INSTALLATION_SESSION_KEY)
        return instance
