"""插件服务：CRUD / OpenAPI 解析 / 端点管理 / 租户配置 / 连通性测试"""
from __future__ import annotations

from sqlalchemy.orm import Session

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
from app.utils.plugin_executor import execute_plugin_call

_SUPPORTED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}

# 候选目录的返回上限。候选面是给用户挑选的，不应无界返回——插件数量增长时
# 响应体会线性膨胀。超限时应通过 keyword / plugin_type 收窄，而不是翻页：
# 用户的挑选动作是一次性的，翻页只会割裂候选的整体视图。
MAX_BINDABLE_PLUGINS = 200


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
        plugin_type: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
    ):
        query = self.db.query(Plugin).filter(self._base_filter(include_public))
        if plugin_type:
            query = query.filter(Plugin.plugin_type == plugin_type)
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
        plugin_type: str | None = None,
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
        if plugin_type:
            query = query.filter(Plugin.plugin_type == plugin_type)
        if keyword:
            query = query.filter(Plugin.name.like(f"%{keyword}%"))

        plugins = (
            query.order_by(Plugin.plugin_type, Plugin.name)
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
            plugin_type=data.plugin_type,
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
        rows = (
            self.db.query(PluginConfig)
            .filter(
                PluginConfig.plugin_id == plugin_id,
                PluginConfig.tenant_id == self.tenant_id,
            )
            .all()
        )
        return {r.name: r.value for r in rows}

    def get_config(self, plugin_id: str) -> PluginConfigResponse:
        self._get_or_404(plugin_id)
        rows = (
            self.db.query(PluginConfig)
            .filter(
                PluginConfig.plugin_id == plugin_id,
                PluginConfig.tenant_id == self.tenant_id,
            )
            .all()
        )
        items = [PluginConfigItem(name=r.name, value=r.value) for r in rows]
        return PluginConfigResponse(items=items)

    def update_config(self, plugin_id: str, req) -> PluginConfigResponse:
        self._get_or_404(plugin_id)
        for item in req.items:
            existing = (
                self.db.query(PluginConfig)
                .filter(
                    PluginConfig.plugin_id == plugin_id,
                    PluginConfig.tenant_id == self.tenant_id,
                    PluginConfig.name == item.name,
                )
                .first()
            )
            if existing:
                existing.value = item.value
            else:
                self.db.add(
                    PluginConfig(
                        plugin_id=plugin_id,
                        tenant_id=self.tenant_id,
                        name=item.name,
                        value=item.value,
                    )
                )
        self.db.flush()
        return self.get_config(plugin_id)

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
