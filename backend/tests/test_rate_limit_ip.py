"""
S7 限流客户端 IP 提取测试。

验证：
- 信任由受信反向代理（nginx）基于 $remote_addr 写入的 X-Real-IP；
- 不再信任客户端可控的 X-Forwarded-For（防止伪造不同 XFF 绕过限流）；
- 无代理 / 开发环境下回退到 TCP 对端地址。
"""
from app.middleware.rate_limit import RateLimitMiddleware


class _Headers:
    def __init__(self, d):
        self._d = d

    def get(self, k):
        return self._d.get(k)


class _Client:
    def __init__(self, host):
        self.host = host


class _Req:
    def __init__(self, headers, client):
        self.headers = headers
        self.client = client


def _req(headers, client_host):
    client = _Client(client_host) if client_host is not None else None
    return _Req(_Headers(headers), client)


def test_trusted_x_real_ip_wins_over_spoofed_xff():
    req = _req(
        {"X-Real-IP": "203.0.113.9", "X-Forwarded-For": "1.2.3.4, 203.0.113.9"},
        "10.0.0.1",
    )
    assert RateLimitMiddleware._get_client_ip(req) == "203.0.113.9"


def test_no_proxy_falls_back_to_tcp_peer():
    req = _req({}, "192.168.1.50")
    assert RateLimitMiddleware._get_client_ip(req) == "192.168.1.50"


def test_spoofed_xff_without_real_ip_is_not_trusted():
    # 仅客户端伪造 X-Forwarded-For、无 X-Real-IP 时，必须回退到 TCP 对端，
    # 绝不可采用伪造值（否则攻击者可用不同 XFF 绕过限流）。
    req = _req({"X-Forwarded-For": "9.9.9.9"}, "10.0.0.5")
    assert RateLimitMiddleware._get_client_ip(req) == "10.0.0.5"


def test_missing_client_and_headers_returns_unknown():
    req = _req({}, None)
    assert RateLimitMiddleware._get_client_ip(req) == "unknown"
