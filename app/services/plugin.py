"""插件服务：CRUD / OpenAPI 解析 / 端点管理 / 租户配置 / 连通性测试"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.plugin import Plugin, PluginConfig, PluginEndpoint
from app.schemas.plugin import (
    PluginCreate,
    PluginUpdate,
    PluginEndpointCreate,
    PluginEndpointUpdate,
    PluginConfigItem,
    PluginConfigResponse,
    PluginTestRequest,
    PluginTestResult,
)
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)
from app.core.plugin_policy import (
    AGENT_EXPOSABLE_PLUGIN_STATUSES,
    BINDABLE_SOURCE_TYPES,
    check_plugin_bindable,
)
from app.core.tenant_scope import public_or_tenant_filter
from app.utils.encryption import encrypt, decrypt
from app.utils.plugin_executor import execute_plugin_call

_SUPPORTED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}

# 候选目录的返回上限。候选面是给用户挑选的，不应无界返回——插件数量增长时
# 响应体会线性膨胀。超限时应通过 keyword / source_type 收窄，而不是翻页：
# 用户的挑选动作是一次性的，翻页只会割裂候选的整体视图。
MAX_BINDABLE_PLUGINS = 200

# 敏感配置项名称的子串（命中即视为密钥，回显脱敏、存储加密）。
_SECRET_KEY_HINTS = (
    "key", "secret", "token", "password", "pwd", "credential",
    "authorization", "auth",
)


def _is_secret_key(name: str) -> bool:
    return any(hint in name.lower() for hint in _SECRET_KEY_HINTS)


def _mask_config(value: Any, name_hint: str = "") -> Any:
    """递归脱敏：命中敏感键名的字符串叶子替换为 "********"，结构（dict/list）保留。"""
    if isinstance(value, dict):
        return {k: _mask_config(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_config(v) for v in value]
    if isinstance(value, str) and value and _is_secret_key(name_hint):
        return "********"
    return value


class PluginService:
    def __init__(self, db: Session, tenant_id: str, is_platform_admin: bool = False):
        self.db = db
        self.tenant_id = tenant_id
        self.is_platform_admin = is_platform_admin

    # ── 公共查询过滤 ─────────────────────────────────────────────────────────

    def _base_filter(self, include_public: bool = False):
        # 复用全局租户过滤器的公共行可见性规则（与 Plugin.__tenant_scope_clause__ 一致），
        # 消除手写 or_(tenant_id == X, tenant_id.is_(None)) 的语义分歧。
        return public_or_tenant_filter(Plugin, self.tenant_id, include_public=include_public)

    def _get_or_404(self, plugin_id: str) -> Plugin:
        plugin = (
            self.db.query(Plugin)
            .filter(self._base_filter(include_public=True), Plugin.id == plugin_id)
            .first()
        )
        if not plugin:
            raise NotFoundException("Plugin", plugin_id)
        return plugin

    # ── 插件 CRUD ───────────────────────────────────────────────────────────

    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        include_public: bool = True,
        source_type: str | None = None,
        status: str | None = None,
    ):
        query = self.db.query(Plugin).filter(self._base_filter(include_public))
        if source_type:
            query = query.filter(Plugin.source_type == source_type)
        if status:
            query = query.filter(Plugin.status == status)
        total = query.count()
        items = (
            query.order_by(Plugin.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def get(self, plugin_id: str) -> Plugin:
        plugin = self._get_or_404(plugin_id)
        endpoints = (
            self.db.query(PluginEndpoint)
            .filter(PluginEndpoint.plugin_id == plugin.id)
            .order_by(PluginEndpoint.created_at)
            .all()
        )
        plugin._endpoints = endpoints  # type: ignore[attr-defined]
        return plugin

    # ── Agent 可绑定候选目录 ────────────────────────────────────────────────

    def list_bindable_for_agent(
        self,
        keyword: str | None = None,
        limit: int = MAX_BINDABLE_PLUGINS,
    ) -> list[tuple[Plugin, list[PluginEndpoint]]]:
        """返回可授权给 Agent 的插件候选：``[(plugin, endpoints), ...]``。

        这是**设计期**的候选面，回答「用户能给 Agent 选什么」，而非「仓库里有什么」。
        裁剪条件与写入校验共用 ``check_plugin_bindable``，保证「选得到」与「存得下」
        永远一致：

        - 状态为 ``active``（``disabled`` / ``pending_review`` 不进候选）；
        - 接入方式已实现（``source_type=http``；``mcp`` / ``skill`` 的执行器未落地）；
        - 至少有一个端点（无端点即无可授权的内容）；
        - 归属为本租户或平台公共插件。

        端点按插件一次性批量查出后分组，避免逐个插件查询造成的 N+1。
        返回上限见 ``MAX_BINDABLE_PLUGINS``。
        """
        query = self.db.query(Plugin).filter(
            self._base_filter(include_public=True),
            Plugin.status.in_(sorted(AGENT_EXPOSABLE_PLUGIN_STATUSES)),
            Plugin.source_type.in_(sorted(BINDABLE_SOURCE_TYPES)),
        )
        if keyword:
            query = query.filter(Plugin.name.like(f"%{keyword}%"))

        plugins = (
            query.order_by(Plugin.name)
            .limit(max(1, limit))
            .all()
        )
        if not plugins:
            return []

        grouped: dict[str, list[PluginEndpoint]] = {}
        endpoints = (
            self.db.query(PluginEndpoint)
            .filter(PluginEndpoint.plugin_id.in_([p.id for p in plugins]))
            .order_by(PluginEndpoint.created_at)
            .all()
        )
        for endpoint in endpoints:
            grouped.setdefault(endpoint.plugin_id, []).append(endpoint)

        result: list[tuple[Plugin, list[PluginEndpoint]]] = []
        for plugin in plugins:
            plugin_endpoints = grouped.get(plugin.id, [])
            # 用同一判据复核一次：SQL 已过滤状态与接入方式，此处补齐「端点数量」条件，
            # 并确保后续若新增裁剪条件时无需在两处同步修改。
            if check_plugin_bindable(
                plugin.status, plugin.source_type, len(plugin_endpoints)
            ):
                continue
            result.append((plugin, plugin_endpoints))
        return result

    def create(self, data: PluginCreate) -> Plugin:
        if data.is_public and not self.is_platform_admin:
            raise ForbiddenException("plugin", "create_public")
        plugin = Plugin(
            tenant_id=None if data.is_public else self.tenant_id,
            name=data.name,
            source_type=data.source_type,
            version=data.version,
            description=data.description,
            config_schema=data.config_schema,
            icon=data.icon,
            author=data.author,
            homepage_url=data.homepage_url,
            api_spec=data.api_spec,
            is_public=data.is_public,
            status=data.status,
        )
        self.db.add(plugin)
        self.db.flush()

        # 若提供了 OpenAPI 规范，自动解析生成端点
        if data.api_spec:
            self._sync_endpoints_from_spec(plugin)
        return plugin

    def update(self, plugin_id: str, data: PluginUpdate) -> Plugin:
        plugin = self._get_or_404(plugin_id)
        if plugin.tenant_id is None and not self.is_platform_admin:
            raise ForbiddenException("plugin", "update")

        if data.is_public is not None:
            if data.is_public and not self.is_platform_admin:
                raise ForbiddenException("plugin", "create_public")
            plugin.is_public = data.is_public
            if data.is_public:
                plugin.tenant_id = None

        update_fields = data.model_dump(exclude={"is_public"}, exclude_none=True)
        for key, value in update_fields.items():
            setattr(plugin, key, value)
        self.db.flush()
        return plugin

    def delete(self, plugin_id: str) -> None:
        plugin = self._get_or_404(plugin_id)
        if plugin.tenant_id is None and not self.is_platform_admin:
            raise ForbiddenException("plugin", "delete")
        # 级联删除端点与租户配置
        self.db.query(PluginEndpoint).filter(
            PluginEndpoint.plugin_id == plugin.id
        ).delete(synchronize_session=False)
        self.db.query(PluginConfig).filter(
            PluginConfig.plugin_id == plugin.id
        ).delete(synchronize_session=False)
        self.db.delete(plugin)
        self.db.flush()

    # ── OpenAPI 规范解析 ──────────────────────────────────────────────────────

    def _sync_endpoints_from_spec(self, plugin: Plugin) -> int:
        """解析插件 OpenAPI 规范，生成/补全端点记录。返回新增端点数量。"""
        spec = plugin.api_spec or {}
        paths = spec.get("paths") or {}
        if not isinstance(paths, dict):
            return 0

        existing = {
            (e.method.upper(), e.endpoint)
            for e in self.db.query(PluginEndpoint).filter(
                PluginEndpoint.plugin_id == plugin.id
            ).all()
        }

        created = 0
        for path, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, op in methods.items():
                if method.upper() not in _SUPPORTED_METHODS:
                    continue
                if (method.upper(), path) in existing:
                    continue
                op = op or {}
                request_body_schema = None
                rb = op.get("requestBody")
                if isinstance(rb, dict):
                    content = rb.get("content") or {}
                    for ctype, cval in content.items():
                        if isinstance(cval, dict) and "schema" in cval:
                            request_body_schema = cval["schema"]
                            break
                self.db.add(
                    PluginEndpoint(
                        plugin_id=plugin.id,
                        endpoint=path,
                        method=method.upper(),
                        headers=None,
                        request_body_schema=request_body_schema,
                        response_schema=None,
                        description=op.get("summary") or op.get("description"),
                    )
                )
                created += 1
        if created:
            self.db.flush()
        return created

    def import_endpoints_from_spec(self, plugin_id: str) -> int:
        plugin = self._get_or_404(plugin_id)
        if not plugin.api_spec:
            raise ValidationException("插件未配置 OpenAPI 规范，无法解析端点")
        return self._sync_endpoints_from_spec(plugin)

    # ── 端点管理 ─────────────────────────────────────────────────────────────

    def list_endpoints(self, plugin_id: str) -> list[PluginEndpoint]:
        self._get_or_404(plugin_id)
        return (
            self.db.query(PluginEndpoint)
            .filter(PluginEndpoint.plugin_id == plugin_id)
            .order_by(PluginEndpoint.created_at)
            .all()
        )

    def add_endpoint(self, plugin_id: str, data: PluginEndpointCreate) -> PluginEndpoint:
        self._get_or_404(plugin_id)
        endpoint = PluginEndpoint(
            plugin_id=plugin_id,
            endpoint=data.endpoint,
            method=data.method.upper(),
            headers=data.headers,
            request_body_schema=data.request_body_schema,
            response_schema=data.response_schema,
            description=data.description,
        )
        self.db.add(endpoint)
        self.db.flush()
        return endpoint

    def update_endpoint(
        self, plugin_id: str, ep_id: str, data: PluginEndpointUpdate
    ) -> PluginEndpoint:
        self._get_or_404(plugin_id)
        endpoint = (
            self.db.query(PluginEndpoint)
            .filter(PluginEndpoint.id == ep_id, PluginEndpoint.plugin_id == plugin_id)
            .first()
        )
        if not endpoint:
            raise NotFoundException("PluginEndpoint", ep_id)
        update_fields = data.model_dump(exclude_none=True)
        for key, value in update_fields.items():
            if key == "method":
                value = value.upper()
            setattr(endpoint, key, value)
        self.db.flush()
        return endpoint

    def delete_endpoint(self, plugin_id: str, ep_id: str) -> None:
        self._get_or_404(plugin_id)
        endpoint = (
            self.db.query(PluginEndpoint)
            .filter(PluginEndpoint.id == ep_id, PluginEndpoint.plugin_id == plugin_id)
            .first()
        )
        if not endpoint:
            raise NotFoundException("PluginEndpoint", ep_id)
        self.db.delete(endpoint)
        self.db.flush()

    # ── 租户级配置 ───────────────────────────────────────────────────────────

    def _load_config_dict(self, plugin_id: str) -> dict:
        """运行时消费：返回解密后的真实配置值（供执行器发请求使用）。

        优先读 ``value_encrypted`` 密文并解密；legacy 行（迁移前、无密文）回退到明文
        ``value``。解密失败时回退到脱敏值（不含明文），避免泄露。
        """
        rows = (
            self.db.query(PluginConfig)
            .filter(
                PluginConfig.plugin_id == plugin_id,
                PluginConfig.tenant_id == self.tenant_id,
            )
            .all()
        )
        out: dict = {}
        for r in rows:
            if r.value_encrypted:
                try:
                    out[r.name] = json.loads(decrypt(r.value_encrypted))
                except Exception:
                    out[r.name] = r.value  # 解密失败：脱敏值（无明文）
            else:
                out[r.name] = r.value  # legacy 明文
        return out

    def get_config(self, plugin_id: str) -> PluginConfigResponse:
        """读取配置（回显）。敏感值永不回显明文/占位，仅以 ``has_value`` 告知已设置（review §3.2）。"""
        self._get_or_404(plugin_id)
        rows = (
            self.db.query(PluginConfig)
            .filter(
                PluginConfig.plugin_id == plugin_id,
                PluginConfig.tenant_id == self.tenant_id,
            )
            .all()
        )
        items = [self._config_item_for_echo(r) for r in rows]
        return PluginConfigResponse(items=items)

    @staticmethod
    def _config_item_for_echo(row: PluginConfig) -> PluginConfigItem:
        """构造回显项：敏感项 value 恒为 None + has_value=True；非敏感项回显真实值。"""
        present = row.value_encrypted is not None or row.value is not None
        if present and _is_secret_key(row.name):
            # 敏感项不回显任何值（明文或脱敏占位都不暴露），前端据此渲染「已设置/点击修改」
            return PluginConfigItem(name=row.name, value=None, has_value=True)
        return PluginConfigItem(name=row.name, value=PluginService._masked_value(row), has_value=present)

    @staticmethod
    def _masked_value(row: PluginConfig) -> Any:
        """回显时的脱敏值（仅用于非敏感项）：legacy 明文行即时脱敏。"""
        if row.value_encrypted is None and row.value is not None:
            return _mask_config(row.value)
        return row.value

    def update_config(self, plugin_id: str, req) -> PluginConfigResponse:
        """写入租户配置（明确契约，review P1-C1 / §3.2 / P1-C4）。

        语义：
        - ``items`` 按 name upsert（新增或覆盖）；
        - ``remove`` 显式删除指定配置项；
        - 提交前校验 ``config_schema`` 的 required（缺失即抛 ``ValidationException``，整次失败）；
        - 真实值以 Fernet 密文落库（``value_encrypted``），``value`` 仅保留脱敏结构。
        """
        plugin = self._get_or_404(plugin_id)

        # 1. 计算最终配置集合（现有 + 传入 - 待删除），用于 required 校验。
        #    传入值为 None 视为「未改动」：不覆盖既有值（避免前端回显空值/脱敏占位时
        #    把真实凭据误写成空），也用于「敏感项不回显、留空即保留」的契约。
        existing_rows = (
            self.db.query(PluginConfig)
            .filter(
                PluginConfig.plugin_id == plugin_id,
                PluginConfig.tenant_id == self.tenant_id,
            )
            .all()
        )
        incoming = {it.name: it.value for it in req.items if it.value is not None}
        final = {r.name: r.value for r in existing_rows}
        final.update(incoming)
        for name in req.remove or []:
            final.pop(name, None)

        # 2. required 校验（fail-closed，早于任何写入）
        self._validate_required(plugin.config_schema, set(final.keys()))

        # 3. 应用：先删待移除项，再 upsert 传入项（跳过 value=None）
        if req.remove:
            self.db.query(PluginConfig).filter(
                and_(
                    PluginConfig.plugin_id == plugin_id,
                    PluginConfig.tenant_id == self.tenant_id,
                    PluginConfig.name.in_(req.remove),
                )
            ).delete(synchronize_session=False)
        for item in req.items:
            if item.value is None:
                continue
            self._upsert_config_row(plugin_id, item.name, item.value)
        self.db.flush()
        return self.get_config(plugin_id)

    def _upsert_config_row(self, plugin_id: str, name: str, value: Any) -> None:
        """写入单行配置：密文落库 + 脱敏结构回显。"""
        ciphertext = encrypt(json.dumps(value, ensure_ascii=False))
        masked = _mask_config(value, name)
        existing = (
            self.db.query(PluginConfig)
            .filter(
                PluginConfig.plugin_id == plugin_id,
                PluginConfig.tenant_id == self.tenant_id,
                PluginConfig.name == name,
            )
            .first()
        )
        if existing:
            existing.value_encrypted = ciphertext
            existing.value = masked
        else:
            self.db.add(
                PluginConfig(
                    plugin_id=plugin_id,
                    tenant_id=self.tenant_id,
                    name=name,
                    value_encrypted=ciphertext,
                    value=masked,
                )
            )

    @staticmethod
    def _validate_required(schema: Optional[dict], present_names) -> None:
        """校验 config_schema.required 中的字段是否均已提供（review P1-C4）。"""
        if not schema:
            return
        required = schema.get("required") or []
        if not required:
            return
        missing = [r for r in required if r not in present_names]
        if missing:
            raise ValidationException(f"缺少必填配置项：{', '.join(missing)}")

    # ── 测试 / 调用 ──────────────────────────────────────────────────────────

    def test(self, plugin_id: str, request: PluginTestRequest) -> PluginTestResult:
        plugin = self._get_or_404(plugin_id)
        config_values = self._load_config_dict(plugin_id)

        # 指定端点 -> 实际调用该端点
        if request.endpoint:
            endpoint = (
                self.db.query(PluginEndpoint)
                .filter(
                    PluginEndpoint.plugin_id == plugin_id,
                    PluginEndpoint.endpoint == request.endpoint,
                )
                .first()
            )
            if not endpoint:
                raise NotFoundException("PluginEndpoint", request.endpoint)
            method = request.method or endpoint.method
            result = execute_plugin_call(
                plugin_name=plugin.name,
                api_spec=plugin.api_spec,
                endpoint_path=endpoint.endpoint,
                method=method,
                endpoint_headers=endpoint.headers,
                config_values=config_values,
                params=request.params,
            )
            return PluginTestResult(**result)

        # 未指定端点 -> 服务连通性探测（GET 基址）
        base_url = config_values.get("base_url")
        if not base_url:
            servers = (plugin.api_spec or {}).get("servers") or []
            base_url = servers[0]["url"] if servers else None
        if not base_url:
            raise ValidationException("插件未配置服务地址，无法探测连通性")

        result = execute_plugin_call(
            plugin_name=plugin.name,
            api_spec=plugin.api_spec,
            endpoint_path="/",
            method="GET",
            endpoint_headers=None,
            config_values=config_values,
            params=None,
            timeout=10,
        )
        return PluginTestResult(**result)
