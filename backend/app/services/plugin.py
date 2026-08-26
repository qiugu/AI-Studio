"""插件服务：CRUD / OpenAPI 解析 / 端点管理 / 租户配置 / 连通性测试"""
from __future__ import annotations

from sqlalchemy import or_
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
from app.utils.plugin_executor import execute_plugin_call

_SUPPORTED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


class PluginService:
    def __init__(self, db: Session, tenant_id: str, is_platform_admin: bool = False):
        self.db = db
        self.tenant_id = tenant_id
        self.is_platform_admin = is_platform_admin

    # ── 公共查询过滤 ─────────────────────────────────────────────────────────

    def _base_filter(self, include_public: bool = False):
        if include_public:
            return or_(
                Plugin.tenant_id == self.tenant_id,
                Plugin.tenant_id.is_(None),
            )
        return Plugin.tenant_id == self.tenant_id

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
        status: str | None = None,
    ):
        query = self.db.query(Plugin).filter(self._base_filter(include_public))
        if plugin_type:
            query = query.filter(Plugin.plugin_type == plugin_type)
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

    def create(self, data: PluginCreate) -> Plugin:
        if data.is_public and not self.is_platform_admin:
            raise ForbiddenException("plugin", "create_public")
        plugin = Plugin(
            tenant_id=None if data.is_public else self.tenant_id,
            name=data.name,
            plugin_type=data.plugin_type,
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
