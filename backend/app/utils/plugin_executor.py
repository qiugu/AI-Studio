"""插件沙盒执行器：封装对插件外部 HTTP 接口的调用。

职责：
- 解析插件 base_url（优先使用租户配置中的 base_url，其次使用 OpenAPI servers）
- **出站安全校验**：请求前经 ``utils/net_guard`` 校验最终 URL，拒绝内网/环回/
  云元数据等地址（SSRF 防护），且不跟随重定向（重定向可绕过校验目标）
- 合并请求头（端点默认头 + 租户配置，如鉴权信息）
- 替换路径参数（值做 URL 编码，防止路径注入）、组装查询参数 / 请求体
- 超时控制与统一错误处理
"""
from typing import Optional, Dict, Any
from urllib.parse import quote, urljoin
import time

import httpx

from app.core.exceptions import BadRequestException
from app.utils.net_guard import assert_outbound_url_allowed

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
    """将 {param} 形式的路径参数替换为实际值。

    替换值做 URL 编码（``/`` 也会被编码）：参数来自模型或调用方，
    若原样拼进路径，``../`` 之类的取值可越出既定端点、甚至借 ``//host``
    改写请求目标。编码后注入面收敛为「单个路径段」。

    注意：此处用 ``list(...)`` 物化后再遍历。此前直接遍历 ``params.items()``
    并在循环内 ``pop``，一旦命中路径参数就会抛
    ``RuntimeError: dictionary changed size during iteration``，
    导致带路径参数的插件调用从未真正成功过。
    """
    path = endpoint_path
    for key, value in list((params or {}).items()):
        placeholder = "{" + key + "}"
        if placeholder in path:
            path = path.replace(placeholder, quote(str(value), safe=""))
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

    Raises:
        BadRequestException: 缺少服务地址，或最终 URL 未通过出站安全校验
            （协议非 http/https、指向内网/环回/云元数据等受限网段）。
    """
    config_values = config_values or {}
    params = dict(params or {})

    base_url = _resolve_base_url(api_spec, config_values)
    if not base_url:
        raise BadRequestException(f"插件「{plugin_name}」缺少服务地址（base_url 或 OpenAPI servers）")

    path = _substitute_path(endpoint_path, params)
    url = urljoin(base_url + "/", path.lstrip("/"))
    headers = _merge_headers(endpoint_headers, config_values)

    # 必须在路径参数替换之后校验最终 URL：urljoin 可能被 "//host" 形态的路径
    # 改写主机名，早于此处校验会留下绕过口子。
    assert_outbound_url_allowed(url)

    method = method.upper()
    request_kwargs: Dict[str, Any] = {"headers": headers, "timeout": timeout}

    if method in ("GET", "DELETE", "HEAD"):
        request_kwargs["params"] = params
    else:
        request_kwargs["json"] = params

    start = time.monotonic()
    try:
        with httpx.Client(follow_redirects=False) as client:
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
