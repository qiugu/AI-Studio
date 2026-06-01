from fastapi import HTTPException


class AppException(HTTPException):
    def __init__(self, status_code: int, error_code: str, message: str):
        self.error_code = error_code
        super().__init__(status_code=status_code, detail=message)


class BadRequestException(AppException):
    def __init__(self, message: str = "Bad request"):
        super().__init__(400, "BAD_REQUEST", message)


class NotFoundException(AppException):
    def __init__(self, resource: str, resource_id: int | None = None):
        msg = f"{resource} not found"
        if resource_id is not None:
            msg += f" (id={resource_id})"
        super().__init__(404, "NOT_FOUND", msg)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(401, "UNAUTHORIZED", message)


class ForbiddenException(AppException):
    def __init__(self, resource: str = "", action: str = ""):
        msg = f"Permission denied: {action} on {resource}" if resource else "Permission denied"
        super().__init__(403, "FORBIDDEN", msg)


class ValidationException(AppException):
    def __init__(self, message: str):
        super().__init__(422, "VALIDATION_ERROR", message)


class QuotaExceededException(AppException):
    def __init__(self, resource: str):
        super().__init__(429, "QUOTA_EXCEEDED", f"Quota exceeded for {resource}")


class LLMException(AppException):
    def __init__(self, message: str):
        super().__init__(502, "LLM_ERROR", message)


class TenantDisabledException(AppException):
    def __init__(self):
        super().__init__(403, "TENANT_DISABLED", "Tenant is disabled")


class TenantNotFoundException(AppException):
    def __init__(self):
        super().__init__(403, "TENANT_NOT_FOUND", "Tenant not found or has been deleted")


class ConflictException(AppException):
    def __init__(self, message: str):
        super().__init__(409, "CONFLICT", message)
