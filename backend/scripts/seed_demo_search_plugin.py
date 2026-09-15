#!/usr/bin/env python
"""插件系统示例：种入「GitHub 搜索（示例）」插件。

背景与定位
----------
插件的完整链路是「**OpenAPI 规范 → 端点 → 入参 Schema → 授权给 Agent → 模型按 Schema
填参 → 执行器发出站请求**」。链路中任何一环缺少可参照的实现，使用者都只能靠读源码
反推。本脚本把这条链路**完整地实例化一份**：一个免密钥、返回 JSON、可真实调用的搜索
插件，既能在界面上直接试用，也可作为编写自有插件的模板。

为什么选 GitHub 搜索作为示例
----------------------------
示例必须**免配置即可跑通**，否则「示例」会退化成「待你准备好密钥后再看」。在若干候选
中（DuckDuckGo InstantAnswer / Wikipedia / StackExchange / GitHub），只有 GitHub
同时满足：

1. **免密钥可用**——`/search/repositories`、`/search/users` 匿名即可调用；
2. **返回结构化 JSON**——搜索类 API 若只返回 HTML，执行器会把整页 HTML 当作字符串
   塞进模型上下文，示例反而误导使用者以为「插件就是抓网页」；
3. **具备真实搜索语义**——有查询词、排序、分页，足以演示入参 Schema 的表达力；
4. **可与需鉴权的端点对照**——`/search/code` 必须带令牌，正好演示可选敏感配置项
   （加密落库、永不回显）的实际意义。

用法
----
容器内执行（推荐，容器具备真实出站能力）::

    docker exec -e PYTHONPATH=/app -w /app ai-studio-backend \
        python scripts/seed_demo_search_plugin.py --tenant-name admin

只查看将要写入的插件定义（不落库）::

    python scripts/seed_demo_search_plugin.py --print-spec

幂等性
------
重复执行不会产生重复插件或重复端点：插件按 ``(tenant_id, name)`` 定位，存在则更新
``api_spec`` / ``config_schema`` / 描述；端点按 ``(plugin_id, method, endpoint)`` 定位，
存在则更新入参与请求头。因此修改本脚本后重跑即可把变更推送到已有插件上。

与内置导入器的分工
------------------
``PluginService.import_endpoints_from_spec`` 是**只增不改**的（已存在的
``(method, path)`` 直接跳过），便于在界面上手工微调过的端点不被覆盖。本脚本面向
「定义即事实」的种子场景，需要**每次都对齐**，因此自行实现 upsert；两者的差异见
``docs/plugin-demo-search.md`` 的「可改进点」。另外内置导入器不从 OpenAPI 读取端点级
请求头，本脚本在 upsert 时显式补齐 ``User-Agent`` —— GitHub 要求所有 API 请求携带该头。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# ── 插件定义 ─────────────────────────────────────────────────────────────────

PLUGIN_NAME = "GitHub 搜索（示例）"
PLUGIN_DESCRIPTION = (
    "插件系统示例插件：通过 GitHub 开放搜索 API 搜索代码仓库、用户与组织、代码片段。"
    "免密钥可用；配置访问令牌后可提升速率上限并解锁「搜索代码」端点。"
    "定义与用法见 docs/plugin-demo-search.md。"
)
PLUGIN_AUTHOR = "AI Studio"
PLUGIN_HOMEPAGE = "https://docs.github.com/rest/search"
PLUGIN_ICON = "search"
PLUGIN_VERSION = "1.0.0"

# 端点级请求头：由平台在执行器合并进每次请求（端点头 + 租户配置头 + api_key）。
# User-Agent 是 GitHub 的硬性要求；Accept / X-GitHub-Api-Version 用于固定返回格式与
# 语义版本，避免 GitHub 调整默认行为后示例静默失效。
_ENDPOINT_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "ai-studio-plugin-demo",
}

CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "base_url": {
            "type": "string",
            "title": "服务地址",
            "description": (
                "留空则回退到 api_spec.servers 的默认值 https://api.github.com。"
                "改为 GitHub Enterprise 地址即可指向自建实例。"
            ),
            "default": "https://api.github.com",
        },
        "api_key": {
            "type": "string",
            "title": "访问令牌（可选）",
            "description": (
                "匿名调用限 10 次/分钟；配置令牌后为 30 次/分钟，并解锁「搜索代码」端点。"
                "名称含 key，平台按敏感项处理：密文落库、回显时 value 恒为空。"
            ),
        },
        # 说明：执行器还支持 `api_key_header` 覆盖凭据请求头名（默认 Authorization，按
        # Bearer 发送）。示例刻意不暴露该项——GitHub 接受 Bearer，多一个开关只会增加
        # 认知负担；且平台前端的敏感项判定是「键名或标题含 key/secret/token/password」
        # 的启发式匹配，`api_key_header` 会被误判为敏感项并渲染成密码框，反而造成困惑。
        # 需要自定义鉴权头的场景，用下面的 headers 直接声明即可。
        "headers": {
            "type": "object",
            "title": "附加请求头（可选）",
            "description": '例如 {"User-Agent": "my-agent"}；与端点级请求头合并，同键以本处为准。',
        },
    },
    # 刻意留空：base_url 在 api_spec.servers 已有回退值，设为必填会让插件在「零配置」
    # 状态下不可用——而「装完即用、再按需加配置」才是示例应有的体验。
    # 想验证必填校验（review P1-C4）时，把需要的键名加进本数组再保存即可。
    "required": [],
}

# 端点入参的公共片段：平台约定把 GET 的入参 Schema 也放在 requestBody 下
# （导入器读取 requestBody.content["application/json"].schema；执行器对 GET 会把
# 非路径参数拼到查询串）。详见 docs/plugin-demo-search.md §2.3。
_PAGE_SIZE_PROP = {
    "type": "integer",
    "title": "返回条数",
    "description": "1-100，匿名调用建议不超过 30；不传则用服务端默认值 30。",
}

_PATHS: dict[str, Any] = {
    "/search/repositories": {
        "get": {
            "summary": "搜索代码仓库",
            "description": "按关键词搜索 GitHub 仓库，返回 star / fork / 语言 / 描述等元数据。",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "q": {
                                    "type": "string",
                                    "title": "搜索关键词",
                                    "description": (
                                        "支持 GitHub 搜索限定符，例如 "
                                        "\"vector database language:rust stars:>1000\"。"
                                    ),
                                },
                                "sort": {
                                    "type": "string",
                                    "title": "排序字段",
                                    "description": "stars / forks / help-wanted-issues / updated；不传按最佳匹配。",
                                },
                                "order": {
                                    "type": "string",
                                    "title": "排序方向",
                                    "description": "desc（默认）或 asc。",
                                },
                                "per_page": _PAGE_SIZE_PROP,
                            },
                            "required": ["q"],
                        }
                    }
                },
            },
            "responses": {"200": {"description": "仓库搜索结果"}},
        }
    },
    "/search/users": {
        "get": {
            "summary": "搜索用户与组织",
            "description": "按关键词搜索 GitHub 用户或组织，返回登录名、类型与主页地址。",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "q": {
                                    "type": "string",
                                    "title": "搜索关键词",
                                    "description": "支持限定符，例如 \"location:china followers:>1000\"。",
                                },
                                "sort": {
                                    "type": "string",
                                    "title": "排序字段",
                                    "description": "followers / repositories / joined；不传按最佳匹配。",
                                },
                                "order": {
                                    "type": "string",
                                    "title": "排序方向",
                                    "description": "desc（默认）或 asc。",
                                },
                                "per_page": _PAGE_SIZE_PROP,
                            },
                            "required": ["q"],
                        }
                    }
                },
            },
            "responses": {"200": {"description": "用户搜索结果"}},
        }
    },
    "/search/code": {
        "get": {
            "summary": "搜索代码（需配置访问令牌）",
            "description": (
                "按关键词搜索代码片段。GitHub 要求该端点必须鉴权，且关键词需含限定符"
                "（如 repo:owner/name 或 org:name），否则返回 422。"
            ),
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "q": {
                                    "type": "string",
                                    "title": "搜索关键词",
                                    "description": "必须含限定符，例如 \"repo:langchain-ai/langchain add_messages\"。",
                                },
                                "per_page": _PAGE_SIZE_PROP,
                            },
                            "required": ["q"],
                        }
                    }
                },
            },
            "responses": {
                "200": {"description": "代码搜索结果"},
                "401": {"description": "未配置访问令牌"},
            },
        }
    },
}

_SERVER_URL = "https://api.github.com"

# 端点路径 -> 端点级请求头。内置导入器不读 OpenAPI 的请求头定义，故在此显式声明，
# 由脚本在 upsert 端点时写入。
ENDPOINT_HEADERS: dict[str, dict[str, str]] = {
    path: dict(_ENDPOINT_HEADERS) for path in _PATHS
}

ACTIONABLE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def build_api_spec() -> dict[str, Any]:
    """构造插件的 OpenAPI 规范。

    ``servers`` 是执行器解析 ``base_url`` 的**回退来源**（租户未配置 ``base_url`` 时使用），
    因此即便示例不要求任何配置，也必须给出。
    """
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "GitHub Search API",
            "version": "2022-11-28",
            "description": "GitHub 开放搜索 API 的示例子集（仓库 / 用户 / 代码）。",
        },
        "servers": [{"url": _SERVER_URL, "description": "GitHub 公共 API"}],
        "paths": _PATHS,
    }


def iter_endpoints() -> list[dict[str, Any]]:
    """把 ``paths`` 展开为端点清单 ``[{endpoint, method, request_body_schema, ...}]``。"""
    out: list[dict[str, Any]] = []
    for path, methods in _PATHS.items():
        for method, op in methods.items():
            if method.upper() not in ACTIONABLE_METHODS:
                continue
            schema = (
                ((op or {}).get("requestBody") or {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            out.append(
                {
                    "endpoint": path,
                    "method": method.upper(),
                    "request_body_schema": schema,
                    "description": (op or {}).get("summary") or (op or {}).get("description"),
                    "headers": ENDPOINT_HEADERS.get(path),
                }
            )
    return out


# ── 种入逻辑 ─────────────────────────────────────────────────────────────────


def _resolve_tenant_id(db, tenant_id: str | None, tenant_name: str | None) -> str:
    from app.models.tenant import Tenant

    if tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise SystemExit(f"未找到租户 id={tenant_id}")
        return tenant.id
    tenant = db.query(Tenant).filter(Tenant.name == (tenant_name or "admin")).first()
    if not tenant:
        names = [t.name for t in db.query(Tenant).all()]
        raise SystemExit(f"未找到租户 name={tenant_name}；现有租户：{names}")
    return tenant.id


def _upsert_endpoints(svc, plugin_id: str, dry_run: bool) -> dict[str, int]:
    """按 ``(plugin_id, method, endpoint)`` upsert 端点；返回新增 / 更新计数。

    刻意不复用 ``import_endpoints_from_spec``：后者只增不改，无法把入参 Schema 的
    变更推送到已存在的端点上（见模块 docstring 的「与内置导入器的分工」）。
    """
    from app.schemas.plugin import PluginEndpointCreate, PluginEndpointUpdate

    existing = {
        (e.method.upper(), e.endpoint): e for e in svc.list_endpoints(plugin_id)
    }
    created = updated = 0
    for spec in iter_endpoints():
        key = (spec["method"], spec["endpoint"])
        current = existing.get(key)
        if current is None:
            created += 1
            if not dry_run:
                svc.add_endpoint(plugin_id, PluginEndpointCreate(**spec))
            continue
        # 仅当确有差异才写入，避免每次重跑都产生无意义的 UPDATE 与 updated_at 抖动。
        changed = (
            (current.request_body_schema or None) != (spec["request_body_schema"] or None)
            or (current.headers or None) != (spec["headers"] or None)
            or (current.description or None) != (spec["description"] or None)
        )
        if changed:
            updated += 1
            if not dry_run:
                svc.update_endpoint(
                    plugin_id,
                    current.id,
                    PluginEndpointUpdate(
                        request_body_schema=spec["request_body_schema"],
                        headers=spec["headers"],
                        description=spec["description"],
                    ),
                )
    return {"created": created, "updated": updated, "total": len(iter_endpoints())}


def seed(
    db,
    *,
    tenant_id: str | None = None,
    tenant_name: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """把示例插件种入指定租户；返回结果摘要。幂等：重复执行只做必要的增量更新。"""
    from app.models.plugin import Plugin
    from app.schemas.plugin import PluginCreate, PluginUpdate
    from app.services.plugin import PluginService

    resolved_tenant = _resolve_tenant_id(db, tenant_id, tenant_name)
    svc = PluginService(db, resolved_tenant)

    existing = (
        db.query(Plugin)
        .filter(Plugin.tenant_id == resolved_tenant, Plugin.name == PLUGIN_NAME)
        .first()
    )

    api_spec = build_api_spec()
    # source_type 固定为 http：本插件走 HTTP 执行器，也是当前唯一已实现的接入方式。
    fields = {
        "source_type": "http",
        "version": PLUGIN_VERSION,
        "description": PLUGIN_DESCRIPTION,
        "config_schema": CONFIG_SCHEMA,
        "icon": PLUGIN_ICON,
        "author": PLUGIN_AUTHOR,
        "homepage_url": PLUGIN_HOMEPAGE,
        "api_spec": api_spec,
        "status": "active",
    }

    if existing is None:
        created = True
        if dry_run:
            plugin_id = "(dry-run)"
            endpoint_stats = {"created": len(iter_endpoints()), "updated": 0, "total": len(iter_endpoints())}
        else:
            plugin = svc.create(PluginCreate(name=PLUGIN_NAME, is_public=False, **fields))
            db.flush()
            plugin_id = plugin.id
            endpoint_stats = _upsert_endpoints(svc, plugin_id, dry_run=False)
    else:
        created = False
        plugin_id = existing.id
        if not dry_run:
            svc.update(plugin_id, PluginUpdate(**fields))
        endpoint_stats = _upsert_endpoints(svc, plugin_id, dry_run=dry_run)

    if not dry_run:
        db.commit()

    return {
        "tenant_id": resolved_tenant,
        "plugin_id": plugin_id,
        "plugin_name": PLUGIN_NAME,
        "created": created,
        "dry_run": dry_run,
        "endpoints": endpoint_stats,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="种入「GitHub 搜索（示例）」插件")
    parser.add_argument("--tenant-id", help="目标租户 id（与 --tenant-name 二选一）")
    parser.add_argument("--tenant-name", default=None, help="目标租户名，默认 admin")
    parser.add_argument("--dry-run", action="store_true", help="只计算差异，不写库")
    parser.add_argument("--print-spec", action="store_true", help="只打印插件定义 JSON，不连数据库")
    args = parser.parse_args(argv)

    if args.print_spec:
        print(
            json.dumps(
                {
                    "name": PLUGIN_NAME,
                    "source_type": "http",
                    "version": PLUGIN_VERSION,
                    "description": PLUGIN_DESCRIPTION,
                    "icon": PLUGIN_ICON,
                    "author": PLUGIN_AUTHOR,
                    "homepage_url": PLUGIN_HOMEPAGE,
                    "config_schema": CONFIG_SCHEMA,
                    "api_spec": build_api_spec(),
                    "endpoints": iter_endpoints(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    # 注意：项目的工厂变量名是 `sessionLocal`（不是 SQLAlchemy 文档里的 `SessionLocal`）。
    from app.core.database import sessionLocal

    db = sessionLocal()
    try:
        result = seed(
            db,
            tenant_id=args.tenant_id,
            tenant_name=args.tenant_name,
            dry_run=args.dry_run,
        )
    finally:
        db.close()

    verb = "将写入（dry-run）" if result["dry_run"] else "已写入"
    action = "新建" if result["created"] else "更新既有"
    eps = result["endpoints"]
    print(f"{verb}｜{action}插件：{result['plugin_name']}")
    print(f"  tenant_id : {result['tenant_id']}")
    print(f"  plugin_id : {result['plugin_id']}")
    print(
        f"  端点      : 共 {eps['total']}｜脚本补建 {eps['created']}｜对齐 {eps['updated']}"
    )
    if result["created"] and not result["dry_run"]:
        # 新建时 PluginService.create 会解析 api_spec.paths 自动导入端点，
        # 因此「脚本补建 0」是正常结果而非漏建。
        print("              （新建插件时端点已由 OpenAPI 规范自动导入，脚本仅做头部/入参对齐）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
