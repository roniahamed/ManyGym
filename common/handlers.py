from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from common.exceptions import (
    DomainException,
    DomainValidationError,
    UnauthorizedContextError,
    ResourceConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
)


def custom_exception_handler(exc, context):
    """
    Unified exception handler mapping DRF exceptions and domain exceptions
    to a standardized JSON response envelope:
    {
        "code": "ERROR_CODE",
        "message": "Detailed error explanation",
        "details": {}
    }
    """
    # First handle DomainException subclasses raised from services
    if isinstance(exc, DomainException):
        status_map = {
            DomainValidationError: status.HTTP_400_BAD_REQUEST,
            UnauthorizedContextError: status.HTTP_401_UNAUTHORIZED,
            PermissionDeniedError: status.HTTP_403_FORBIDDEN,
            ResourceNotFoundError: status.HTTP_404_NOT_FOUND,
            ResourceConflictError: status.HTTP_409_CONFLICT,
        }
        http_status = status_map.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
            status=http_status,
        )

    # Call REST framework's default exception handler to get the standard error response
    response = exception_handler(exc, context)

    if response is not None:
        code = "API_ERROR"
        message = "An error occurred while processing your request."
        details = {}

        if response.status_code == status.HTTP_400_BAD_REQUEST:
            code = "VALIDATION_ERROR"
            message = "Validation failed for the submitted data."
            details = response.data
        elif response.status_code == status.HTTP_401_UNAUTHORIZED:
            code = "AUTHENTICATION_REQUIRED"
            message = "Authentication credentials were not provided or are invalid."
            details = response.data
        elif response.status_code == status.HTTP_403_FORBIDDEN:
            code = "PERMISSION_DENIED"
            message = "You do not have permission to perform this action."
            details = response.data
        elif response.status_code == status.HTTP_404_NOT_FOUND:
            code = "NOT_FOUND"
            message = "The requested resource was not found."
            details = response.data
        elif response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
            code = "METHOD_NOT_ALLOWED"
            message = f"Method {context['request'].method} not allowed for this endpoint."
            details = response.data
        elif response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            code = "THROTTLED"
            message = "Request was throttled due to rate limiting."
            details = response.data
        else:
            details = response.data

        response.data = {
            "code": code,
            "message": message,
            "details": details,
        }

    return response
