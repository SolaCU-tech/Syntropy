"""One error shape for the whole API (spec section 11): a code, a plain-language message, and
field-level details.

    {"code": "invalid", "message": "Some fields need attention.", "details": {"name": [...]}}
"""

from typing import Any

from rest_framework import exceptions, serializers
from rest_framework.response import Response
from rest_framework.views import exception_handler


class ErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField(required=False)


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    response = exception_handler(exc, context)
    if response is None or not isinstance(exc, exceptions.APIException):
        return response

    if isinstance(exc, exceptions.ValidationError):
        body: dict[str, Any] = {
            "code": "invalid",
            "message": "Some fields need attention.",
            "details": exc.detail if isinstance(exc.detail, dict) else {"non_field": exc.detail},
        }
    else:
        codes = exc.get_codes()
        body = {
            "code": codes if isinstance(codes, str) else exc.default_code,
            "message": str(exc.detail),
        }
    response.data = body
    return response
