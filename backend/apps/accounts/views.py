from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import installations
from .models import DeviceInstallation, normalize_email
from .serializers import InstallationSerializer, LoginSerializer, UserSerializer


@method_decorator([never_cache, ensure_csrf_cookie], name="dispatch")
class CsrfView(APIView):
    """Issue the CSRF cookie the SPA must echo on state-changing requests."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={204: None})
    def get(self, request: Request) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)


# DRF only enforces CSRF for already-authenticated sessions. Login is
# anonymous, so it is protected explicitly to prevent login CSRF.
@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def get_authenticate_header(self, request: Request) -> str:
        # No authenticator runs here, so tell DRF to answer bad credentials
        # with 401 rather than downgrading them to 403.
        return "Session"

    @extend_schema(request=LoginSerializer, responses=UserSerializer)
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=normalize_email(serializer.validated_data["email"]),
            password=serializer.validated_data["password"],
        )
        if user is None:
            # One message for unknown email, wrong password and disabled
            # account, so the endpoint cannot be used to discover accounts.
            raise AuthenticationFailed("Incorrect email or password.", code="invalid_credentials")
        login(request, user)  # rotates the session key and the CSRF token
        installation = installations.bind_session_to_installation(request, user)
        response = Response(UserSerializer(user).data)
        installations.set_installation_cookie(response, installation)
        return response


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        logout(request)  # flushes the server-side session
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    @extend_schema(responses=UserSerializer)
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)


class InstallationListView(APIView):
    """The signed-in user's own browser installations."""

    @extend_schema(responses=InstallationSerializer(many=True))
    def get(self, request: Request) -> Response:
        queryset = DeviceInstallation.objects.filter(user=request.user)
        serializer = InstallationSerializer(queryset, many=True, context={"request": request})
        return Response(serializer.data)


class InstallationRevokeView(APIView):
    """Revoke one of your own installations; its sessions end immediately."""

    @extend_schema(request=None, responses=InstallationSerializer)
    def post(self, request: Request, installation_id) -> Response:
        installation = installations.revoke_installation(
            user=request.user, installation_id=installation_id
        )
        data = InstallationSerializer(installation, context={"request": request}).data
        if installation.pk == request.auth.pk:
            logout(request)  # the caller revoked the browser they are using
        return Response(data)
