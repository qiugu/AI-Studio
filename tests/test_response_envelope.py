"""
C2 统一异常信封测试。

验证：
- AppException 派生类在信封中携带 ``error_code`` 业务码；
- 普通 HTTPException 无 ``error_code``（信封结构仍一致）；
- ``code`` 取 HTTP 状态码，前端仅需按 ``code === 0`` 判定成功。
"""
from fastapi import HTTPException

from app.core.exceptions import (
    AppException,
    BadRequestException,
    NotFoundException,
    build_error_envelope,
)


def test_app_exception_envelope_carries_error_code():
    exc = NotFoundException("agent", 42)
    env = build_error_envelope(exc)
    assert env["code"] == 404
    assert env["error_code"] == "NOT_FOUND"
    assert env["message"] == "agent not found (id=42)"
    assert env["data"] is None


def test_app_exception_base_envelope():
    exc = AppException(400, "BAD_REQUEST", "oops")
    env = build_error_envelope(exc)
    assert env["code"] == 400
    assert env["error_code"] == "BAD_REQUEST"
    assert env["message"] == "oops"


def test_plain_http_exception_has_no_error_code():
    exc = HTTPException(status_code=401, detail="unauthorized")
    env = build_error_envelope(exc)
    assert env["code"] == 401
    assert "error_code" not in env
    assert env["message"] == "unauthorized"
    assert env["data"] is None


def test_bad_request_exception_envelope():
    # C1：knowledge.py 等已改用 BadRequestException（保留 400），信封结构须一致。
    exc = BadRequestException("Unsupported file type: pdf")
    env = build_error_envelope(exc)
    assert env["code"] == 400
    assert env["error_code"] == "BAD_REQUEST"
    assert env["message"] == "Unsupported file type: pdf"
    assert env["data"] is None
