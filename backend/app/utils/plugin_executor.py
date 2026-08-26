"""插件沙盒执行器：封装对插件外部 HTTP 接口的调用。

职责：
- 解析插件 base_url（优先使用租户配置中的 base_url，其次使用 OpenAPI servers）
- 合并请求头（端点默认头 + 租户配置，如鉴权信息）
- 替换路径参数、组装查询参数 / 请求体
- 超时控制与统一错误处理
"""
from typing import Optional, Dict, Any
from urllib.parse import urljoin
import time

import httpx

from app.core.exceptions import BadRequestException

DEFAULT_TIMEOUT = 30


def _resolve_base_url(api_spec: Optional[dict], config_values: Dict[str, Any]) -> Optional[str]:
    """解析插件服务基址。"""
    base_url = config_values.get("base_url")
    if base_url:
        return str(base_url).rstrip("/")
    servers = (api_spec or {}).get("servers") or []
    for s in servers:
        url = s.get("url") if isinstance(s, dict) else None
        if url:
            return str(url).rstrip("/")
    return None


def _merge_headers(
    endpoint_headers: Optional[dict], config_values: Dict[str, Any]
) -> Dict[str, str]:
    """合并请求头：端点默认头 + 租户配置中的 headers / api_key。"""
    headers: Dict[str, str] = {}
    if isinstance(endpoint_headers, dict):
        for k, v in endpoint_headers.items():
            headers[str(k)] = str(v)
    cfg_headers = config_values.get("headers")
    if isinstance(cfg_headers, dict):
        for k, v in cfg_headers.items():
            headers[str(k)] = str(v)
    api_key = config_values.get("api_key")
    if api_key and "authorization" not in {k.lower() for k in headers}:
        # 若配置了 api_key_header 则使用自定义头名，否则默认 Bearer
        header_name = config_values.get("api_key_header") or "Authorization"
        headers[str(header_name)] = f"Bearer {api_key}"
    return headers


def _substitute_path(endpoint_path: str, params: Dict[str, Any]) -> str:
    """将 {param} 形式的路径参数替换为实际值。"""
    path = endpoint_path
    for key, value in (params or {}).items():
        placeholder = "{" + key + "}"
        if placeholder in path:
            path = path.replace(placeholder, str(value))
            params.pop(key, None)
    return path


def execute_plugin_call(
    *,
    plugin_name: str,
    api_spec: Optional[dict],
    endpoint_path: str,
    method: str,
    endpoint_headers: Optional[dict] = None,
    config_values: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """执行一次插件端点调用。

    Args:
        plugin_name: 插件名称（用于错误提示）
        api_spec: 插件 OpenAPI 规范
        endpoint_path: 端点路径
        method: HTTP 方法
        endpoint_headers: 端点默认请求头
        config_values: 租户级插件配置（可含 base_url / api_key / headers）
        params: 调用参数（路径参数 / 查询参数 / 请求体）
        timeout: 超时时间（秒）

    Returns:
        dict: { success, status_code, latency_ms, data, error }
    """
    config_values = config_values or {}
    params = dict(params or {})

    base_url = _resolve_base_url(api_spec, config_values)
    if not base_url:
        raise BadRequestException(f"插件「{plugin_name}」缺少服务地址（base_url 或 OpenAPI servers）")

    path = _substitute_path(endpoint_path, params)
    url = urljoin(base_url + "/", path.lstrip("/"))
    headers = _merge_headers(endpoint_headers, config_values)

    method = method.upper()
    request_kwargs: Dict[str, Any] = {"headers": headers, "timeout": timeout}

    if method in ("GET", "DELETE", "HEAD"):
        request_kwargs["params"] = params
    else:
        request_kwargs["json"] = params

    start = time.monotonic()
    try:
        with httpx.Client() as client:
            resp = client.request(method, url, **request_kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return {
            "success": resp.is_success,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "data": body,
            "error": None if resp.is_success else f"HTTP {resp.status_code}",
        }
    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "data": None,
            "error": f"请求超时（>{timeout}s）",
        }
    except httpx.HTTPError as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "data": None,
            "error": f"网络错误：{str(e)}",
        }
