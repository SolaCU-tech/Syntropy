"""Session sign-in for the web app (ADR-24): a Django session cookie plus a CSRF token, served
from the same site. No tokens are ever stored in the browser."""

from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.core.exceptions import ErrorSerializer


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    first_name = serializers.CharField()
    email = serializers.CharField()


class SessionSerializer(serializers.Serializer):
    authenticated = serializers.BooleanField()
    user = UserSerializer(allow_null=True)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=256, trim_whitespace=False)


def _session(request) -> dict:
    user = request.user
    if not user.is_authenticated:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": UserSerializer(user).data}


class LoginThrottle(AnonRateThrottle):
    scope = "login"
    rate = "10/min"


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionView(APIView):
    """Who is signed in. Also sets the CSRF cookie the app sends back on every change."""

    permission_classes = [AllowAny]

    @extend_schema(operation_id="auth_session", responses=SessionSerializer)
    def get(self, request: Request) -> Response:
        return Response(_session(request))


# DRF skips CSRF for anonymous requests; sign-in is checked anyway (login CSRF).
@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(
        operation_id="auth_login",
        request=LoginSerializer,
        responses={200: SessionSerializer, 400: OpenApiResponse(ErrorSerializer)},
    )
    def post(self, request: Request) -> Response:
        body = LoginSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        user = authenticate(request, **body.validated_data)
        if user is None:
            return Response(
                {"code": "invalid_login", "message": "That username and password don't match."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        login(request._request, user)
        request.user = user
        return Response(_session(request))


class LogoutView(APIView):
    @extend_schema(operation_id="auth_logout", request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)
