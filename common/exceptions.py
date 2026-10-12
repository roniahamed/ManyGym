class DomainException(Exception):
    """Base domain exception for Many Gym business logic."""

    default_code = "DOMAIN_ERROR"
    default_message = "A domain business logic error occurred."

    def __init__(self, message=None, code=None, details=None):
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.details = details or {}
        super().__init__(self.message)


class DomainValidationError(DomainException):
    default_code = "VALIDATION_ERROR"
    default_message = "Validation failed for domain requirements."


class UnauthorizedContextError(DomainException):
    default_code = "UNAUTHORIZED_CONTEXT"
    default_message = "The current token context is unauthorized for this operation."


class ResourceConflictError(DomainException):
    default_code = "RESOURCE_CONFLICT"
    default_message = "The requested state conflicts with an existing resource."


class PermissionDeniedError(DomainException):
    default_code = "PERMISSION_DENIED"
    default_message = "You do not possess the required scopes for this gym operation."


class ResourceNotFoundError(DomainException):
    default_code = "RESOURCE_NOT_FOUND"
    default_message = "The requested resource could not be found."
