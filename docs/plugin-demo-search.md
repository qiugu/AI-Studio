# 插件示例：GitHub 搜索

> **文档性质**：示例说明 · **已落地可运行**。
> **前置阅读**：[plugin-types.md](plugin-types.md)（接入方式口径）、[plugin-usage-flow-review.md](plugin-usage-flow-review.md)（治理机制）。
> **一句话**：这是一套**能真跑通**的插件参考实现——定义在 `backend/scripts/seed_demo_search_plugin.py`，在界面上可见、可配置、可测试、可授权给 Agent，且把「OpenAPI 规范 → 端点 → 入参 Schema → 模型填参 → 出站调用」每一步都实例化了一份。

---

## 1. 为什么拿它当示例

示例的第一要求是**免配置即可跑通**——否则「示例」会退化成「等你准备好密钥再看」。候选搜索类 API 实测对比（2026-09-15，容器内实测）：

| 候选 | 免密钥 | 返回形态 | 结论 |
|------|--------|----------|------|
| GitHub Search API | ✅ `/search/repositories`、`/search/users` 匿名可用 | 结构化 JSON | **选用** |
| DuckDuckGo InstantAnswer | ✅ | JSON，但实测返回空 `Abstract`（`http=202`） | 无法演示 |
| Wikipedia / Wikimedia REST | ✅（Rest 版实测 403，要求 User-Agent） | JSON | 域名在本环境解析到受限网段（`2001::1`），被出站护栏拒绝 |
| StackExchange Search | ✅ | 结构化 JSON | 可用，但与本平台业务场景关联弱 |
| Bing / Google / Brave | ❌ 需密钥 | HTML / JSON | 无法免配置演示 |

选 GitHub 的另外两条理由：

1. **搜索语义真实**——有查询词、排序字段、分页，足以演示入参 Schema 的表达力，而不是「一个 query 字符串换一段文本」。
2. **天然带一个需鉴权的端点**——`/search/code` 必须有令牌，正好让**可选敏感配置项**（`api_key` 加密落库、永不回显）有实际意义，而不是纸上功能。

---

## 2. 插件定义解读

### 2.1 插件主体

| 字段 | 值 | 说明 |
|------|-----|------|
| `name` | `GitHub 搜索（示例）` | 名称里保留「示例」二字，便于使用者判断**可以随时删掉** |
| `source_type` | `http` | 当前**唯一**已实现的接入方式。`mcp` / `skill` 的执行器未落地，选了也绑不到 Agent（见 §7） |
| `status` | `active` | 仅 `active` 能进入 Agent 候选目录 |
| `is_public` | `false` | 租户私有。脚本刻意不创建公共插件——公共插件是全租户可见的全局副作用，不适合由种子脚本擅自产生 |
| `config_schema` | 见 §2.2 | 驱动前端动态表单 |
| `api_spec` | OpenAPI 3.0.3 子集 | 既作说明，也是 `base_url` 的回退来源与端点的导入来源 |
| `description` | 含「见 docs/plugin-demo-search.md」 | 让人从界面就能找到这份文档 |

### 2.2 配置 Schema

`config_schema` 决定配置页渲染出哪些控件（前端按 `properties[].title` 作标签、`description` 作说明、`type` 选控件类型）。本示例只有三项：

| 配置项 | 类型 | 必填 | 作用 |
|--------|------|------|------|
| `base_url` | string | ❌ | 留空则回退到 `api_spec.servers[0].url`。**这就是"插件可指向自建实例"的入口**——改这一项即可指向 GitHub Enterprise |
| `api_key` | string | ❌ | 匿名 10 次/分钟 → 有令牌 30 次/分钟，并解锁「搜索代码」端点 |
| `headers` | object | ❌ | 附加请求头，与端点级请求头合并（同键以本处为准） |

**`required` 刻意留空**。这不是遗漏：`base_url` 在 `api_spec.servers` 已有回退值，若把它设为必填，插件在「零配置」状态下就不可用——而「装完即用、再按需加配置」才是示例应有的体验。想验证必填校验（review P1-C4）时，把键名加进 `required` 数组再保存，接口会返回 `缺少必填配置项：base_url`。

**`api_key` 的完整链路**（对应 M1-3 的凭据加密）：

```
填表单 → PUT /plugins/{id}/config → 名称命中敏感启发式(key/secret/token/password)
      → 真实值 Fernet 密文写入 value_encrypted；value 列只留脱敏结构
回显  → GET /plugins/{id}/config → 敏感项 value = null 且 has_value = true
保存  → 前端跳过「空值且原本已设置」的敏感字段 → 不会用空值覆盖真实凭据
```

> **为什么示例不暴露 `api_key_header`**：执行器支持用它覆盖凭据请求头名，但（a）GitHub 接受 `Authorization: Bearer`，多一个开关只增加认知负担；（b）平台的敏感项判定是「**键名或标题**含 key/secret/token/password」的启发式，`api_key_header` 会被误判成敏感项并渲染成密码框，反而造成困惑。需要自定义鉴权头的场景，用 `headers` 直接声明即可。这条启发式的过度匹配已记入 §8。

### 2.3 端点与入参 Schema（平台约定）

三条**必须知道**的平台约定，否则写出来的插件「看着对、跑不通」：

| 约定 | 内容 | 依据 |
|------|------|------|
| **GET 的入参 Schema 也放在 `requestBody` 下** | 导入器只读 `requestBody.content["application/json"].schema`，**不读** OpenAPI 的 `parameters` | `services/plugin.py::_sync_endpoints_from_spec` |
| **非路径参数按方法分流** | GET/DELETE/HEAD → 拼进查询串；其余 → 作为 JSON 请求体 | `utils/plugin_executor.py:125-128` |
| **只有 `required` 或由调用方显式给出的参数才会被发送** | 工具层用 `{k: v for k, v in kwargs.items() if v is not None}` 过滤；JSON Schema 的 `default` **不会**被消费 | `services/agent.py::_build_langchain_tools` |

第三条的直接后果：`request_body_schema` 里**可选**参数（如 `per_page`）若模型不填，就是「不发送」，由远端服务用它的默认值——这通常正是想要的。但**不要让请求能否成立依赖某个可选参数**：远端若没有默认值，请求会缺参。

本示例的三个端点：

| 方法 | 端点 | 入参（`q` 必填） | 说明 |
|------|------|------------------|------|
| GET | `/search/repositories` | `q`、`sort`、`order`、`per_page` | 搜索仓库 |
| GET | `/search/users` | `q`、`sort`、`order`、`per_page` | 搜索用户与组织 |
| GET | `/search/code` | `q`、`per_page` | 搜索代码，**需配置令牌** |

写路径参数时用 `{name}` 占位，执行器会做 URL 编码后替换（`/repo/{owner}`），且该键不会再进查询串。

### 2.4 端点级请求头

三个端点都带同一组头：

```json
{"Accept": "application/vnd.github+json",
 "X-GitHub-Api-Version": "2022-11-28",
 "User-Agent": "ai-studio-plugin-demo"}
```

`User-Agent` 是 GitHub 的**硬性要求**（缺失会 403）；另两个用于固定返回格式与语义版本，避免上游改默认行为后示例静默变质。

⚠️ **内置导入器不读 OpenAPI 里的请求头定义**（`_sync_endpoints_from_spec` 写死 `headers=None`），所以脚本在 upsert 端点时显式补齐——这也演示了端点可以直接维护。

---

## 3. 用法

### 3.1 一键种入（推荐）

```bash
# 容器内执行（容器具备真实出站能力）
docker exec -e PYTHONPATH=/app -w /app ai-studio-backend \
    python scripts/seed_demo_search_plugin.py --tenant-name admin

# 只看要写入什么，不落库
docker exec -e PYTHONPATH=/app -w /app ai-studio-backend \
    python scripts/seed_demo_search_plugin.py --tenant-name admin --dry-run

# 只打印插件定义 JSON（不连数据库），便于复制改造
python scripts/seed_demo_search_plugin.py --print-spec
```

实测输出：

```
已写入｜新建插件：GitHub 搜索（示例）
  tenant_id : 3d993ed5-134a-42c7-b859-2b800c5580d0
  plugin_id : 1b4b7cf4-8134-4024-bd0b-02b841060e06
  端点      : 共 3｜脚本补建 0｜对齐 3
              （新建插件时端点已由 OpenAPI 规范自动导入，脚本仅做头部/入参对齐）
```

**幂等**：重复执行不产生重复插件或端点（插件按 `(tenant_id, name)` 定位，端点按 `(plugin_id, method, endpoint)` 定位）；第二次执行输出 `脚本补建 0｜对齐 0`。因此改完脚本重跑即可把变更推送到已有插件。

### 3.2 从界面走一遍（等价流程）

1. **插件 → 新建**：名称随意，**接入方式选 `http`**（选 `mcp`/`skill` 会得到一个绑不到 Agent 的插件，见 §7）；把 `--print-spec` 的 `api_spec` 粘进 API 规范。
2. 保存后端点会被自动解析出来（3 个）；也可在「插件端点」里手工新增 / 用「导入端点」再次解析。
3. **配置**页会按 `config_schema` 渲染出「服务地址 / 访问令牌 / 附加请求头」三个控件。可全部留空。
4. **测试插件**：选端点 → 填参数 → 执行，当场看到真实返回。
5. 回到 **Agent → 编辑 → 工具**，在「插件工具」里就能选到它（见 §4）。

---

## 4. 接入 Agent

### 4.1 候选目录的裁剪条件

`GET /agent/agents/tool-catalog` 只返回**四条件同时满足**的插件：归属本租户或公共、`status=active`、`source_type` 已实现、**至少一个端点**。这与写入校验共用同一组判据（`core/plugin_policy.py`），因此「选得到」与「存得下」永远一致。

实测该目录只列出示例插件——同租户下另有一个 `source_type=mcp` 的插件被正确裁掉。

### 4.2 绑定时必须显式选端点

平台**不提供**「未指定则取第一个端点」的兜底：端点语义不确定，而 OpenAPI 规范里破坏性端点（`DELETE`）常排在前面，兜底等于把最危险的端点当默认值。未指定端点的工具在构建期就被跳过（fail-closed），实测构建出的工具数为 `0`。

### 4.3 模型实际看到什么

工具描述 = 你在绑定处填的 `description` **+ 平台自动追加的参数提示**；入参结构来自端点的 `request_body_schema`。实测：

```
工具名      : github_search_repos
工具描述    : 在 GitHub 上搜索代码仓库，返回仓库名、star 数、语言与描述；参数：q:string、sort:string、order:string、per_page:integer
args_schema : ['q', 'sort', 'order', 'per_page']
    - q        : <class 'str'>            required=True
    - sort     : Optional[str]            required=False
    - order    : Optional[str]            required=False
    - per_page : Optional[int]            required=False
```

**绑定处的描述要写「什么时候用、返回什么」**，参数名与类型平台会补，但语义只能靠你写——`request_body_schema` 里各属性的 `description` 目前**不会**进工具描述（见 §8）。

---

## 5. 实测运行记录

来自容器内的接口层与工具层验证（`ai-studio-backend`，2026-09-15）：

| # | 验证点 | 结果 |
|---|--------|------|
| 1 | `GET /plugins` | 200，列表可见 `GitHub 搜索（示例） source_type=http status=active` |
| 2 | `GET /plugins/{id}` | 200，3 个端点，`props` 与 `headers` 与定义一致；`config_schema.required=[]`；`servers=[https://api.github.com]` |
| 3 | `POST /plugins/{id}/test` `/search/repositories` `{q:"vector database", sort:"stars", per_page:3}` | **`success=true status=200 latency=354ms`**，`total_count=13851`，首条 `redis/redis`（star 76364）、次条 `milvus-io/milvus`（46110） |
| 4 | 同上 `/search/users` `{q:"location:china followers:>5000", per_page:3}` | **`success=true status=200 latency=442ms`**，`total_count=103`，首条 `ruanyf` |
| 5 | 同上 `/search/code` | `status=401`，`{"message":"Requires authentication"}` —— **符合设计**：该端点必须配置令牌 |
| 6 | `GET /agent/agents/tool-catalog` | 200，仅示例插件在列；3 个端点可选 |
| 7 | 配置写入 + 回显 | `api_key` → `{"value": null, "has_value": true}`（密文落库、不回显）；`base_url` → 回显真实值。（演示后已清理，未留数据） |
| 8 | 工具构建 + 真实调用（模型视角） | 工具名/描述/`args_schema` 见 §4.3；`tool.func(q="vector database", sort="stars", per_page=2)` 返回真实 JSON（`redis/redis`、`milvus-io/milvus`） |
| 9 | 只填必填项 | `tool.func(q="llm agent framework")` → 返回 30 条（远端默认值），证明可选参数被正确省略 |
| 10 | 未指定端点 | 构建出的工具数 `0`（fail-closed + 警告日志） |
| 11 | 多端点绑定 | 同一插件授权 2 个端点 → 2 个独立工具；用户搜索端点返回 `total_count=42`、首条 `ruanyf` |

> **重要提醒**：上表第 8–11 项走的是 `tool.func(...)` **直调**，它绕过了 LangChain 的
> `_to_args_and_kwargs` 入参转换。该示例插件是项目里**第一个绑定工具的 Agent**，
> 接入真实对话链路后立刻暴露出 4 个叠加缺陷（模板缺 `{tool_names}` 直接崩、单入参
> `Tool` 承载不了结构化参数、`ToolException: Too many arguments`、流式取不到逐字内容），
> **在 2026-09-15 修复前，「绑定工具后对话」这条路径不可能成功**。
> 详见 [plugin-usage-flow-review.md §8.7](plugin-usage-flow-review.md#87-带工具对话链路的缺陷修复2026-09-15已落地)。
> 修复后已在本示例上通过服务层与 HTTP/SSE 层双重实跑（真实模型 + 真实 GitHub 调用）。

---

## 6. 改造成你自己的搜索插件

模板只有三处需要动：

**(1) 换服务地址**——`_SERVER_URL` / `api_spec.servers[0].url`。指向自建实例时，让 `base_url` 保持可选、由 `api_spec.servers` 给默认值；或反过来把 `base_url` 加进 `required`，强制使用者显式填。

**(2) 换端点与入参**——改 `_PATHS`：`paths[路径][方法]`，入参 Schema 放进 `requestBody.content["application/json"].schema`，必填项列进 `required`。带密钥的服务（SearXNG / 博查 / Tavily / Bing 之类）形状完全一致，典型如：

```python
"/search": {
    "post": {
        "summary": "网络搜索",
        "requestBody": {"required": True, "content": {"application/json": {"schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "title": "查询词"},
                "count": {"type": "integer", "title": "返回条数"},
            },
            "required": ["query"],
        }}}},
    }
}
```
配 `config_schema` 里的 `api_key` + `base_url` 两项即可（`api_key` 会按 Bearer 注入 `Authorization`）。

**(3) 换端点级请求头**——改脚本里的 `_ENDPOINT_HEADERS`（`ENDPOINT_HEADERS` 由它按端点路径展开）。多数服务不需要请求头，删掉即可。

改完重跑 `seed_demo_search_plugin.py`，脚本会把定义与端点对齐到已有插件上。

**写插件时必须注意的三点**（都来自 §2.3 的平台约定）：

- GET 的入参 Schema 放在 `requestBody`，不要只写 `parameters`——后者当前不会被解析；
- 不要在端点路径里写查询串（如 `?action=query`）：**该查询串会被静默丢弃**，见 §8 第 1 条；
- 请求能否成立不要依赖可选参数：可选参数模型不填就等于不发送。

---

## 7. ⚠️ 与既有「搜索工具」插件的关系

本租户下另有一个插件：`搜索工具`（`source_type=mcp`，`id=8d7b8232-5b72-4ae4-85b4-2ee3824602ce`，创建于 2026-09-15 09:59，`api_spec` 为空、端点数 0）。

**它当前不可用，且不是配置问题**：

| 障碍 | 原因 | 何时可用 |
|------|------|----------|
| 不在 Agent 候选目录里 | `source_type=mcp`，而 `BINDABLE_SOURCE_TYPES = {http}`——`mcp` 执行器未落地，放进候选等于让用户选到「跑不通」的项 | M2.3（MCP 客户端适配器）完成后 |
| 即便强行绑定也会被运行时跳过 | 运行时门禁 0 会以同一判据拒绝 | 同上 |
| 无端点 | 缺失 API 规范，没有任何内容可授权 | 补上 `api_spec` 或手工加端点 |

**处理建议**（三选一，需你确认）：

1. **删除**它，改用本示例——最干净；
2. **保留但改造**：`source_type` 改成 `http`，把本示例的 `api_spec` 贴进去，秒变可用；
3. **留作 M2.3 的验收样本**：等 MCP 执行器落地后拿它验证 `mcp` 链路。

---

## 8. 构建示例时暴露出的可改进点

按严重度排序，均已定位到代码位置。

### 8.1 🔴 端点路径中的查询串会被静默丢弃

`plugin_executor.py:125-128` 对 GET 一律设置 `request_kwargs["params"] = params`（**即便是空字典**），而 httpx 在 `params is not None` 时会**整体替换** URL 自带的查询串。实测：

```
路径 URL : .../search/repositories?sort=stars&order=desc&per_page=2
params={}                → 实际 URL : .../search/repositories          ← 查询串全丢
params={'q':'llm'}       → 实际 URL : .../search/repositories?q=llm    ← 只剩 q
params=None              → 实际 URL : .../search/repositories?sort=stars&order=desc&per_page=2
```

后果：那些**必须带固定查询参数**的 API（MediaWiki 的 `action=query&format=json`、带 `api-version=` 的服务）无法被正确表达。叠加 §8.2 的「导入器不读 `parameters`」，固定查询参数既放不进规范、也写不进路径——**当前无任何合法位置可放**。

修复方向（小改动，建议单独一轮）：在 `execute_plugin_call` 里把「路径自带查询串 + 动态 params」显式合并，而非让 httpx 覆盖；或至少在 `params` 为空时不传该键。

### 8.2 🟡 导入器不读 `parameters`，也不读端点级请求头

`services/plugin.py::_sync_endpoints_from_spec` 只解析 `requestBody`。这与 OpenAPI 习惯相悖（GET 的查询参数标准位置是 `parameters`），于是平台只能约定「GET 的入参也写进 `requestBody`」——一个对使用者不自然的约定。同一函数还写死 `headers=None`，端点级请求头只能靠脚本或界面手工补。

建议：`parameters` 映射为入参 Schema（`in: query` → 查询参数，`in: path` → 路径参数），并在导入时一并读取请求头定义。

### 8.3 🟡 入参 Schema 的 `description` / `default` 未被消费；`enum` 也未传给模型

`_build_args_schema` 只取 `properties` 的 `type` 与 `required`，忽略 `description`、`default`、`enum`。于是工具描述里只有 `q:string、sort:string` 这类干巴巴的类型提示，模型不知道 `sort` 能填 `stars`/`forks`、`q` 支持 GitHub 限定符——**表达力被浪费**，只能靠绑定处的描述文字补救。

建议：把 `properties[].description` 追加进工具描述（或生成 `Field(description=...)`），`enum` 渲染为可选值列表。

### 8.4 🟡 前端敏感项判定是纯启发式，会过度匹配

`PluginConfig.tsx:155`：`/key|secret|token|password/i.test(键名 + 标题)`。任何名字或标题沾上这四个词就变密码框——`api_key_header` 就中招（它本身不是秘密）。同时反向也有漏网：叫 `credential`、`passwd` 的键不会被识别。

建议：以「显式声明」取代启发式——在 `config_schema` 的属性上加 `"x-secret": true`，启发式仅作兜底。后端 `_SECRET_KEY_HINTS` 也有同样的两面性问题，应一并调整以免两端口径漂移。

### 8.5 ⚪ 顺手发现的既有缺陷：`scripts/init_knowledge_permissions.py` 导入失败

该脚本 `from app.core.database import SessionLocal`，而模块实际导出的是 `sessionLocal`（小写 s），直接运行会 `ImportError`。与本次交付无关，未改动，留待确认。

---

## 9. 清理

```bash
# 删除示例插件（端点与配置随外键级联删除）
curl -X DELETE -H "Authorization: Bearer <token>" \
    "$BASE/plugins/1b4b7cf4-8134-4024-bd0b-02b841060e06"
```

或在界面上「插件 → 删除」。删除前请先解绑引用它的 Agent 工具。

---

## 附录 · 相关文件

| 用途 | 位置 |
|------|------|
| 插件定义与种入脚本 | `backend/scripts/seed_demo_search_plugin.py` |
| 执行器（出站调用） | `backend/app/utils/plugin_executor.py` |
| 出站护栏（SSRF） | `backend/app/utils/net_guard.py` |
| 暴露策略（门禁） | `backend/app/core/plugin_policy.py` |
| 服务层（导入 / 配置 / 测试） | `backend/app/services/plugin.py` |
| Agent 侧工具构建 | `backend/app/services/agent.py::_build_langchain_tools` |
| 配置页渲染 | `frontend/src/pages/Plugins/PluginConfig.tsx` |
