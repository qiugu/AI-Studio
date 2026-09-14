"""出站请求安全护栏（SSRF 防护）。

**为什么需要**：插件（``utils/plugin_executor.py``）与 Agent 的「API 工具」都允许
**由租户自行配置目标地址**——插件 ``base_url``、OpenAPI ``spec["servers"][0]["url"]``、
API 工具的 ``url``。若不加约束，租户只需把地址写成 ``http://169.254.169.254/...``
或 ``http://10.0.0.5/...``，即可让服务端代为访问内网与云元数据端点，平台随之成为
SSRF 与内网探测的跳板（OWASP LLM06「过度代理」）。

**校验什么**：对**最终将要请求的 URL**逐项校验，任一不通过即抛
``BadRequestException``：

1. 协议白名单：仅 ``http`` / ``https``（拒绝 ``file`` / ``gopher`` / ``ftp`` 等）；
2. 主机名黑名单：``localhost`` 及其子域；
3. 解析主机名取得**全部** IP，任一落入以下范围即拒绝——私有地址、环回、链路本地
   （覆盖 ``169.254.169.254`` 云元数据）、保留、组播、未指定、IPv6 站点本地；
   IPv4-mapped IPv6（形如 ``::ffff:127.0.0.1``）先还原为 IPv4 再判断，
   否则会被误判为「公网地址」；
4. DNS 解析失败即拒绝（fail-closed），避免「解析不出来就放行」。

**残留风险**：校验通过后到真正建立连接之间，DNS 可能被重新解析到内网地址
（DNS rebinding，TOCTOU 窗口）。彻底消除需在连接层固定已校验的 IP，或统一走
出站代理，属二期方案（见 ``docs/plugin-types.md`` 演进表）。因此本模块是**纵深防御
的一层**，不能替代网络层出站策略。

**配置**：``PLUGIN_BLOCK_PRIVATE_NETWORK``（默认 ``true``）。确需让插件访问内网
（如对接内部 CRM）时可将该开关置为 ``false``——这是一次**有意识的降级**，
应同时通过网络层策略限制出站范围。
"""
from __future__ import annotations

import ipaddress
import socket
from typing import List
from urllib.parse import urlsplit

from app.core.config import config
from app.core.exceptions import BadRequestException

# 仅允许标准 web 协议；其余协议（file / gopher / ftp / dict …）既可绕过 IP 校验，
# 也常被用于探测内网服务，一律拒绝。
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# 显式拒绝的主机名。即便解析结果最终会被 IP 校验拦下，提前拒绝能给出更明确的错误，
# 且不依赖本机 hosts / DNS 的解析行为。
_DENIED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

# ``ipaddress`` 的各布尔标志未覆盖的特殊用途网段，需显式列出：
# - 100.64.0.0/10（RFC 6598，运营商级 NAT）：实测 is_private / is_reserved 等
#   标志**全部为 False**，只靠标志位会漏放，故必须显式声明。
_EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),
)


def is_ip_blocked(ip_str: str) -> bool:
    """判断单个 IP 字面量是否属于禁止访问的范围。

    无法解析为 IP 的输入按「拒绝」处理（保守失败），避免守卫被畸形输入绕过。
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True

    # ``::ffff:127.0.0.1`` 这类 IPv4-mapped IPv6，其 is_loopback / is_private
    # 均为 False，必须先还原成 IPv4 再判断。
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped

    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
        or any(ip in network for network in _EXTRA_BLOCKED_NETWORKS)
    )


def _resolve_host_ips(host: str, port: int) -> List[str]:
    """解析主机名对应的全部 IP 字面量；解析失败即拒绝。"""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BadRequestException(f"出站地址无法解析：{host}（{exc}）") from exc
    return sorted({info[4][0] for info in infos})


def assert_outbound_url_allowed(url: str) -> None:
    """校验出站 URL；不允许时抛出 ``BadRequestException``。

    调用方应在**发起请求前**、用**路径参数替换之后**的最终 URL 调用本函数，
    否则形如 ``//169.254.169.254/`` 的路径仍可能通过 ``urljoin`` 改写目标主机。
    """
    if not config.plugin_block_private_network:
        # 显式降级：部署方确认需要访问内网，跳过校验。
        return

    parts = urlsplit(url or "")

    scheme = (parts.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise BadRequestException(f"不允许的出站协议：{scheme or '(空)'}，仅支持 http / https")

    host = parts.hostname
    if not host:
        raise BadRequestException(f"出站地址缺少主机名：{url}")

    hostname = host.lower().rstrip(".")
    if hostname in _DENIED_HOSTNAMES or hostname.endswith(".localhost"):
        raise BadRequestException(f"不允许访问本机回环主机名：{hostname}")

    try:
        port = parts.port
    except ValueError as exc:
        raise BadRequestException(f"出站地址端口非法：{url}") from exc
    if port is None:
        port = 443 if scheme == "https" else 80

    for ip_str in _resolve_host_ips(hostname, port):
        if is_ip_blocked(ip_str):
            raise BadRequestException(
                f"出站地址 {hostname} 解析到受限网段（{ip_str}），已拒绝访问"
            )
