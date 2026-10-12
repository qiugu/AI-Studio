from fastapi import HTTPException


class AppException(HTTPException):
    def __init__(self, status_code: int, error_code: str, message: str):
        self.error_code = error_code
        super().__init__(status_code=status_code, detail=message)


class BadRequestException(AppException):
    def __init__(self, message: str = "Bad request"):
        super().__init__(400, "BAD_REQUEST", message)


class NotFoundException(AppException):
    def __init__(self, resource: str, resource_id: str | int | None = None):
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


def build_error_envelope(exc: "AppException") -> dict:
    """构造统一异常响应信封 ``{code, error_code?, message, data}``。

    - ``code`` 取 HTTP 状态码（成功响应统一为 ``0``），前端无需区分成功/失败的结构，
      仅按 ``code === 0`` 判定成功。
    - ``error_code`` 为业务错误码（字符串），仅 ``AppException`` 派生类携带，
      便于前端按错误类型做差异化处理（如 QUOTA_EXCEEDED 跳转充值页）。
    - 普通 ``HTTPException`` 无 ``error_code``，信封中省略该字段。

    该信封是成功/失败响应的单一权威定义，详见 ``docs/api-design.md``。
    """
    envelope: dict = {
        "code": exc.status_code,
        "message": exc.detail,
        "data": None,
    }
    error_code = getattr(exc, "error_code", None)
    if error_code:
        envelope["error_code"] = error_code
    return envelope
