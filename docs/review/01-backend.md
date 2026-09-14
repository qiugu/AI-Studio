# 01 · 后端评审（安全与租户隔离 / 契约一致性 / 架构与可维护性）

> 范围：`backend/`（Python 3.12 + FastAPI + SQLAlchemy 2.0 + MySQL + Qdrant + Redis + Celery + LangChain）
> 规模：13 个 API 路由文件、20 个 service、5 个 repository、28 个 model、17 个 Alembic 迁移，`backend/app` 合计约 13,187 行

---

## 结论

后端的**骨架是合格的**：分层目录齐备、异常体系有明确设计、JWT 与 API Key 加密实现规范、SSE 格式合规、迁移链完整、依赖版本全量锁定。

问题集中在三点：

1. **安全配置存在高危项**（CORS 通配 + 携带凭证），且有 4 处中等风险。
2. **多租户隔离"已实现但未强制"** —— 隔离逻辑分散在各 service 手工编写，缺少统一机制与自动化校验，已确证 3 处遗漏。
3. **编码约定被系统性绕过** —— `CLAUDE.md`/`AGENTS.md` 明确规定"所有数据访问必须通过 `BaseRepository`""禁止直接抛 `HTTPException`"，实际分别有 49 处与 25 处违反。

---

## 一、安全与租户隔离

### S1 · CORS 通配来源与携带凭证同时开启（P0）

**位置**：`backend/app/main.py:57-63`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**根因**：`allow_origins=["*"]` 与 `allow_credentials=True` 组合时，Starlette 的 `CORSMiddleware` 不会返回字面量 `*`，而是**回显请求方提供的 `Origin`**，同时附带 `Access-Control-Allow-Credentials: true`。这等同于允许**任意站点**以用户身份发起携带 Cookie/凭据的跨域请求。

附带问题：`core/config.py` 中**不存在** CORS 来源配置项（已确认 `Config` 类无相关字段），说明来源列表是硬编码的，无法按环境区分。

**影响**：CSRF 与凭据泄露的载荷放大。即使当前认证使用 `Authorization` 头（不依赖 Cookie），一旦按 S6 建议切换到 Cookie 会话，此配置会立即成为可直接利用的漏洞。因此 S1 与 S6 必须协同整改。

**改进建议**：
1. 在 `core/config.py` 新增 `cors_origins: list[str]`（从环境变量读取，如 `CORS_ORIGINS`），默认值仅含 `http://localhost:5173`、`http://localhost`。
2. `main.py` 改为 `allow_origins=config.cors_origins`。
3. 若确实需要支持凭证，**不得**使用 `allow_origins=["*"]`；改为显式白名单。
4. 同步补充 `backend/.env.example`、根 `.env.example`、`docker-compose.yml` 三处变量。

**验收标准**：携带 `Origin: https://evil.example` 的预检请求，响应头中**不出现** `Access-Control-Allow-Credentials: true`；白名单来源的请求正常通过。

---

### S2 · 细粒度权限校验缺失（P0）

**位置**：`backend/app/api/`

**实测覆盖情况**：

| 路由模块 | 守卫方式 | 评价 |
|----------|----------|------|
| `knowledge.py`、`agent.py`、`workflow.py` | `require_permission(...)` | 符合约定 |
| `role.py`、`user.py`、`system.py`、`admin.py`、`audit.py` | `require_tenant_admin` / `require_platform_admin` | 符合约定 |
| **`ai_provider.py`**、**`ai_model.py`**、**`prompt.py`**、**`plugin.py`** | 仅 `CurrentUser`（只校验登录态） | **缺权限校验** |

证据：`grep -l "require_permission" backend/app/api/` 仅命中 3 个业务模块；上述 4 个模块中 `CurrentUser` 出现 7 / 7 / 10 / 15 次，无任何 `require_permission`。

**根因**：权限点（如 `ai_model:write`）在 `permissions` 表中已存在，但路由层未挂载对应守卫 —— 属"能力已具备、接线遗漏"。

**影响**：租户内**任意已登录成员**（含只读角色 `tenant_member`）均可创建/修改/删除 AI 供应商、模型、Prompt 与插件。若插件可配置外部 API 与凭据（`plugin.py` 含 `PluginConfig`），则越权后果进一步扩大。对应 OWASP API Security Top 10 (2023) 的 API5: Broken Function Level Authorization。

**改进建议**：
1. 为四个模块的写操作补齐 `dependencies=[Depends(require_permission("<resource>", "write"))]`，读操作补 `"read"`。
2. 新增回归测试：以仅具只读角色账号调用写接口，断言返回 403。
3. 建议补充一份"路由 ↔ 权限点"对照表，纳入 CI 校验（配合 D1/D2 的契约门禁）。

**验收标准**：无写权限的账号调用上述 4 个模块的任一写接口，返回 403 且响应体符合统一格式。

---

### S3 · 多租户过滤缺少统一强制机制（P0）

**位置**：`backend/app/services/*`、`backend/app/repositories/base.py`

**事实基础（经精确统计）**：

- services 层直接调用 `self.db.query(...)` / `self.db.execute(...)` 的位置共 **49 处**，分布：

  | 文件 | 处数 |
  |------|------|
  | `services/plugin.py` | 13 |
  | `services/prompt.py` | 8 |
  | `services/agent.py` | 7 |
  | `services/audit.py` | 6 |
  | `services/token_usage.py` | 4 |
  | `services/quota.py` | 3 |
  | `services/ai_provider.py` | 3 |
  | `services/ai_model.py` | 3 |
  | `services/workflow_engine.py` | 2 |

- `repositories/` 仅被 `conversation`、`knowledge`、`workflow`、`agent` 四个 service 使用；`BaseRepository._tenant_filter()`（`repositories/base.py:21-26`）未被业务层复用。
- `middleware/tenant.py:33-85` 的 `TenantMiddleware` **只做**三件事：白名单放行、解析 token 取 `tid`、校验租户状态与软删除，并把 `tenant_id` 写入 `request.state`。它**不提供任何 DB 层过滤**。这是本问题的根因。

**关键澄清（避免误判）**：隔离**并非失效**。绝大多数 service 通过手工方式实现了过滤，例如：

- `services/prompt.py:35-42` 定义了 `_base_query()`，统一附加 `Prompt.tenant_id == self.tenant_id`
- `services/ai_model.py:21-26` 定义 `_base_filter(include_public)`，支持"本租户 + 公共"语义
- `services/audit.py:36,67` 直接 `.filter(AuditLog.tenant_id == self.tenant_id)`

**但存在确证的遗漏与不一致**：

| 位置 | 问题 |
|------|------|
| `services/workflow_engine.py:255` | `self.db.query(AIModel).filter(AIModel.id == model_id).first()` —— **仅按主键过滤** |
| `services/workflow_engine.py:259-262` | 同一函数内紧接着的 `AIProvider` 查询**却有** `AIProvider.tenant_id == self.tenant_id` —— **同一函数内标准不一致** |
| `services/agent.py:82` | `self.db.query(AIModel).filter(AIModel.id == model_id)` —— 仅按主键 |
| `services/agent.py:514` | `self.db.query(AIModel).filter(AIModel.id == agent.model_id)` —— 仅按主键 |

`workflow_engine.py` 内相邻两行采用两套标准，是最有说服力的证据：它说明隔离正确性**完全取决于编写者当次是否记得**，而不是由机制保证。

**影响**：
- 当前风险等级为"中"（`AIModel` 存在公共模型 `tenant_id IS NULL` 语义，且多数调用点的 ID 来自已校验的上下文）。
- 但**演进风险为高**：新增任何查询都可能遗漏过滤，且现有测试（见 [03](03-engineering.md)）**没有任何用例能覆盖到此**，即遗漏不会被发现。

对应 OWASP API Security Top 10 (2023) 的 API1: Broken Object Level Authorization。

**改进建议**（按优先级）：
1. **短期**：修复上述 3 处确证遗漏，统一为"本租户 + 公共"语义（复用 `BaseRepository._tenant_or_public_filter()` 的判定逻辑）。
2. **中期**：为 `services/` 引入静态检查或 lint 规则，禁止裸 `db.query`（可用自定义 ruff 规则或 CI 脚本 `grep` 白名单校验）。
3. **长期**：逐步将 service 迁移到 Repository，使 `_tenant_filter()` 成为唯一入口。
4. **立即**：补充租户隔离回归测试（跨租户访问断言 403 或空结果），这是防止未来回归的最低成本手段。

**验收标准**：
- 上述 3 处遗漏修复，过滤条件与同文件其他位置一致。
- 新增隔离测试：以租户 A 的 token 请求租户 B 的资源 ID，返回 403 或空列表。
- `services/` 下裸 `db.query` 数量降至 0 或经评审进入白名单（并有文档说明原因）。

> **后续（约定对齐）**：全局过滤器（`core/tenant_scope.py`）已强制注入租户条件，原"所有查询必须经 BaseRepository"约定调整为分层约定，公共行可见性统一收敛到 `public_or_tenant_filter(...)`。详见 `docs/plan-convention-alignment.md`（条目 S3）。

---

### S4 · `prompt_versions` 缺 `tenant_id`，隔离为单点依赖（P0）

**位置**：`backend/app/models/prompt_version.py:18`、`backend/app/services/prompt.py:193-199`

```python
# models/prompt_version.py
class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version_number", name="uq_prompt_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, ...)
    prompt_id: Mapped[str] = mapped_column(String(36), ForeignKey("prompts.id", ondelete="CASCADE"), ...)
    # 无 tenant_id 字段
```

```python
# services/prompt.py:193-199
def activate_version(self, prompt_id: str, version_id: str) -> PromptVersion:
    self._get_or_404(prompt_id)                       # ← 租户校验发生在这里
    target = self._get_version_or_404(prompt_id, version_id)
    self.db.query(PromptVersion).filter(          # ← 查询本身无租户条件
        PromptVersion.prompt_id == prompt_id,
        PromptVersion.is_current.is_(True),
    ).update({"is_current": False}, synchronize_session="evaluate")
```

**关键澄清**：评审阶段曾判断此处"可凭 `prompt_id` 猜解越权读取其他租户版本"。**该判断经复核后撤销** —— `_get_or_404(prompt_id)`（`prompt.py:44-48`）会先经 `_base_query()` 校验 `Prompt` 的租户归属，不存在则可绕过。因此**未发现可利用的越权路径**。

**保留的问题性质**：这是**纵深防御缺失**。安全性完全依赖于"每个调用点都先调用了 `_get_or_404`"这一人工约定；一旦新增直接按 `version_id` 查询的入口（例如"按版本 ID 直接预览"类接口），隔离即失效，且与 S3 同理，没有测试能拦截。

**改进建议**：
1. 为 `prompt_versions` 增加 `tenant_id` 列并建索引（Alembic 迁移），历史数据从关联 `prompts.tenant_id` 回填。
2. 所有 `PromptVersion` 查询附加租户条件，与 S3 的改造统一进行。
3. 该迁移必须先于 S3 的 prompt 相关查询改造落地（见路线图依赖）。

**验收标准**：`alembic upgrade head` 成功；存在断言 `prompt_versions` 按 `tenant_id` 过滤的测试；历史数据回填后行数与 `prompts` 关联一致。

---

### S5 · 文件上传校验薄弱，配置项未生效（P0）

**位置**：`backend/app/api/knowledge.py:161-199`、`backend/app/core/config.py:56-57`

**问题分解**：

| 子问题 | 证据 | 说明 |
|--------|------|------|
| 大小限制**完全失效** | `core/config.py:57` 定义 `max_upload_size_mb: int = 50`，全库检索**零引用** | 配置项为装饰性，无任何调用点 |
| 无文件内容校验 | `api/knowledge.py:168-171` 仅比对扩展名白名单 `["txt","pdf","docx","md"]` | 无 magic bytes / content-type 校验，可伪造扩展名 |
| 全量读入内存 | `api/knowledge.py:174-177` `content = await file.read()` | 无流式写入，大文件可致内存耗尽 |
| 落盘目录默认不当 | `core/config.py:56` `upload_dir: str = '/tmp/ai_studio/uploads'` | 系统临时目录，可能被清理，且多实例部署不共享 |
| 异常处理粗糙 | `api/knowledge.py:196` `except:` 裸捕获 | 吞掉所有异常，掩盖真实错误 |
| 路由级防护 | — | `client_max_body_size 100m` 仅在 Nginx 层（`frontend/nginx.conf`），后端无独立防线 |

**影响**：对应 OWASP API Security Top 10 (2023) 的 API4: Unrestricted Resource Consumption 与 API8: Security Misconfiguration。攻击面：伪造扩展名上传非预期内容；超大文件耗尽 worker 内存。

**改进建议**：
1. 在读取前校验 `file.size`（`UploadFile.size` 或读取 `Content-Length`），超限返回 413。
2. 读取时按配置上限**分块**写入临时文件，避免全量驻留内存。
3. 增加 magic bytes 校验（PDF `%PDF-`、DOCX 为 ZIP `PK\x03\x04`），与扩展名双重确认。
4. 将裸 `except:` 改为 `except OSError:` 并记录日志。
5. `upload_dir` 默认值改为项目内路径或强制必填；多实例场景改用对象存储或共享卷。
6. 在 `core/config.py` 定义校验上限后，**必须**存在实际调用点（否则重复本次问题）。

**验收标准**：将二进制内容命名为 `.txt` 上传被拒；上传超过 `MAX_UPLOAD_SIZE_MB` 的文件返回 413；`grep -rn "max_upload_size_mb" backend/app` 至少有一处业务调用（非仅定义处）；正常 `pdf`/`docx` 解析链路不受影响。

---

### S7 · 限流可绕过与降级策略（P1）

**位置**：`backend/app/middleware/rate_limit.py`

**问题分解**：

| 子问题 | 证据 | 说明 |
|--------|------|------|
| 客户端 IP 可伪造 | `_get_client_ip()` 无条件信任 `X-Forwarded-For` 的**第一个**值 | 攻击者每次请求带不同伪造 XFF 即可完全绕过限流 |
| Redis 不可用时放行 | `dispatch()` 中 `if redis is None: return await call_next(request)` | fail-open，Redis 故障即无限流；代码注释亦自陈此设计 |
| 限流粒度 | key 为 `rate_limit:{ip}:{path}` | 按路径分桶，跨路径请求不受全局约束 |
| 路径匹配前缀不严谨 | `path.startswith(p)`，`_AUTH_PATHS` 含 `/auth/login` | `/auth/loginXXX` 亦会命中更严格阈值（影响轻微，属鲁棒性问题） |

**评价**：fail-open 是**有意的可用性取舍**，本身不是缺陷 —— 但必须与业务风险匹配并**显式记录**。当前登录接口的暴力破解防护依赖限流，而该限流既可被伪造 IP 绕过、又会在 Redis 抖动时整体失效，因此对认证场景而言防护强度不足。

**改进建议**：
1. **可信代理白名单**：仅当请求来自已知反向代理（如 Compose 网络内的 `frontend`）时才信任 `X-Forwarded-For`，否则使用 `request.client.host`。生产环境推荐由 Nginx 统一覆写 `X-Real-IP`（当前 `nginx.conf` 已设置 `X-Real-IP`，应改为优先使用它）。
2. **多维度限流**：登录接口增加按账号（email）维度的计数，避免仅依赖 IP。
3. **明确降级策略**：在 README 或 `docs/` 中显式写明 fail-open 的取舍与前提；若登录接口风险不可接受，对认证路径改为 fail-closed（Redis 不可用时拒绝登录请求）。
4. `_AUTH_PATHS` 匹配改为精确匹配或带 `/` 边界的匹配。

**验收标准**：伪造不同 `X-Forwarded-For` 的连续请求仍被同一真实来源的阈值限制；Redis 不可用时的行为与文档描述一致且经测试确认。

---

### 其他安全观察（未单列条目）

| 观察 | 位置 | 说明 |
|------|------|------|
| `jwt_secret_key` 存在公开默认值 | `core/config.py:45` `SecretStr('change-me-in-production')` | 若 `.env` 缺失，将以公开字符串签发 JWT。建议启动时校验：处于非开发环境而密钥为默认值时**拒绝启动** |
| JWT / Fernet / 密码哈希实现规范 | `core/security.py`、`utils/encryption.py` | 使用 PyJWT、`pwdlib.recommended()`、Fernet，密钥取自 `SecretStr`，**未发现硬编码真实密钥** |
| 无 SQL 注入风险 | 全库 | 全部使用 ORM 参数化查询，未发现字符串拼接 SQL |
| 全局异常处理器会记录堆栈 | `main.py:100-110` | 返回体为通用文案，未泄露内部细节，符合预期 |
| 上传路由有权限守卫 | `api/knowledge.py:153-155` | `require_permission("knowledge", "upload")` 已挂载 |

---

## 二、契约与异常一致性

### C1 · 统一响应契约被 25 处裸 `HTTPException` 破坏（P1）

**位置**：`backend/app/api/knowledge.py`（13 处）、`backend/app/api/agent.py`（12 处）

**模式一：反向转换（占比最高，共 23 处）**

```python
except AppException as e:
    raise HTTPException(status_code=e.status_code, detail=e.message)
```

出现于 `api/knowledge.py:47,87,107,130,148,200,257,277,295,333,367` 与 `api/agent.py:58,93,135,154,178,215,235,257,276,448`。

这是**最严重的一种**：service 层正确地抛出了 `AppException`，路由层却把它降级为 `HTTPException`，主动丢弃了统一契约。

**模式二：直接抛出（2 处）**

- `api/knowledge.py:170-173`（不支持的扩展名，400）
- `api/knowledge.py:222`（多文件校验）
- `api/agent.py:113,342`：`raise HTTPException(status_code=e.status_code, detail=str(e))` —— 连 `detail` 都退化为 `str(e)`，把 `AppException.message` 丢掉了

**根因**：`main.py:76-84` 已注册 `AppException` 处理器，返回 `{code, message, data}`。但 `HTTPException` 由 FastAPI 内置处理器处理，返回格式为 `{"detail": "..."}`。二者并存导致**同一 API 在不同失败路径下返回两种响应结构**。

**影响**：
- 前端 `frontend/src/utils/request.ts` 的 `getErrorMessage()` 读取 `error.response.data.message`；走 `HTTPException` 路径时该字段不存在，会退化为通用提示 —— 用户看到"请求失败"而非真实原因。
- 契约文档 `docs/api-design.md` 声明的统一格式与实际不符。
- 对应 OWASP API Security Top 10 (2023) 的 API8 部分维度（不一致的错误暴露），主要是工程质量问题。

**改进建议**：
1. 删除全部 `except AppException → raise HTTPException` 包装，让 `AppException` 直接冒泡到全局处理器（`AppException` 处理器已存在，无需任何转换）。
2. 其余 `raise HTTPException` 改为对应语义的 `AppException` 子类（如 `ValidationException`、`NotFoundException`）。
3. **前置条件**：必须先有测试基线（见 [03](03-engineering.md)），断言"所有错误响应体包含 `code`/`message`/`data`"，否则无法验证改造完整性。

**验收标准**：`grep -rc "raise HTTPException" backend/app/api/` 全部为 0；测试断言任一错误响应均含三个字段；前端错误提示能显示后端返回的真实 `message`。

> **后续（约定对齐）**：`api/` 下 4 处裸 `HTTPException` 已改为 `AppException` 子类（`BadRequestException`），grep 归零；约定符合性由 `docs/plan-convention-alignment.md` 收口（条目 C1）。

---

### C2 · 成功与失败的 `code` 语义不一致（P1）

**位置**：`backend/app/main.py:76-84`、`backend/app/schemas/common.py:7-19`

```python
# schemas/common.py
class ResponseBase(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"

# main.py
@app.exception_handler(AppException)
async def app_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={
        "code": exc.status_code,   # ← 用 HTTP 状态码填充业务 code
        "message": exc.detail,
        "data": None,
    })
```

**问题**：`code=0` 表示成功，异常时 `code` 被填入 HTTP 状态码（403/404/500…）。这使 `code` 字段承载了**两套语义**：成功时是"业务码"，失败时是"HTTP 码"。`docs/api-design.md` 仅声明了 `code: 0` 的成功格式，未定义错误码空间。

**影响**：前端无法通过 `code` 做稳定的业务分支（例如"配额用尽"与"未授权"都可能是 403）；后续若需要区分业务错误类型，将不得不新增字段，造成契约二次变更。

**改进建议**（二选一，需评审定稿）：
- **方案 A（推荐，改动小）**：保留 HTTP 状态码表达传输层语义，`code` 定义独立业务码空间（如 0 成功、1xxx 通用错误、2xxx 配额、3xxx 租户…），并维护一份错误码表。
- **方案 B**：彻底分离 —— 传输层用 HTTP 状态码，响应体仅保留 `message` 与 `data`，移除 `code`。改动面大，需同步前端。

无论选哪个，都必须更新 `docs/api-design.md` 并加入契约测试。

**验收标准**：错误码语义有单一权威定义；成功/失败响应的 `code` 取值域不相交或语义明确；文档与实现一致。

---

### C3 · 使用已废弃参数 `openapi_prefix`（P1）

**位置**：`backend/app/main.py:49`

```python
app = FastAPI(
    title="AI Studio", version="0.1.0",
    openapi_prefix="/api",           # ← 已废弃
    servers=[{"url": "/api", "description": "API Gateway"}],
)
```

**已确认的运行时行为**（读 FastAPI 0.136.1 源码）：
- `fastapi/applications.py:927-947`：`openapi_prefix` 被赋给 `self.root_path`，并发出废弃告警；源码注释为 `# TODO: remove when discarding the openapi_prefix parameter`。
- 因为 `root_path` 生效，Starlette 路由会按 `root_path` 剥离前缀后匹配，因此**开发环境**（`vite.config.ts` 代理 `/api` 且不 rewrite）与**生产环境**（Nginx `proxy_pass http://backend:8000/` 剥离 `/api`）**均能正常工作**。

**因此这不构成功能缺陷**，而是技术债：依赖一个官方标注待移除的参数来维持前端的 `/api` 约定。一旦升级 FastAPI 至移除该参数的版本，开发与生产的路径行为将同时改变。

**改进建议**：
1. 改用 `root_path="/api"`（语义等价、非废弃）。
2. 或更彻底：让后端路由真实挂载在 `/api` 下（`FastAPI(root_path=...)` 由 ASGI 层处理更规范），使前端无需依赖代理剥离。
3. 补充一条冒烟测试：`GET /docs` 与 `GET /api/auth/login`（错误凭据）均返回预期状态码，纳入 CI。

**验收标准**：移除 `openapi_prefix` 后，`/docs`、`/redoc`、前端经代理访问 `/api/**` 均正常；无废弃告警输出。

---

## 三、架构与可维护性

### A3 · 工作流引擎缺整体超时与节点级重试（P1）

**位置**：`backend/app/services/workflow_engine.py`（666 行）

**事实**：全文件检索 `timeout`、`asyncio`、`retry`、`tenacity`、`max_retries` **零命中**。
对照：`backend/app/utils/llm.py:67` 设置了 `kwargs.setdefault("timeout", 600)` —— 事件可见**单次 LLM 调用有 600 秒超时**，但：

- 整个工作流执行**无总时长上限**：N 个节点 × 每个最长 600 秒，可长时间占用 worker。
- 节点级**无重试**：单次网络抖动即导致整个执行失败。
- 无 `asyncio` 相关代码，说明未使用超时包装或并发控制。

**改进建议**：
1. 为执行入口引入整体超时（如 `asyncio.wait_for` 或执行上下文记录起始时间并逐节点检查预算）。
2. 为可重试的节点类型（LLM 调用、HTTP 插件调用）引入基于 `tenacity` 的有限次重试 + 指数退避（`tenacity` 已在 `requirements.txt` 中锁定）。
3. 超时/重试策略作为工作流级配置，而非硬编码。

**验收标准**：构造慢节点场景，整体执行在配置阈值内返回可识别错误并释放资源；节点级失败按策略重试后可观测（日志或执行记录体现重试次数）。

---

### A1 · 超长文件（P2）

| 文件 | 行数 | 说明 |
|------|------|------|
| `backend/app/services/agent.py` | **1194** | 承担 Agent CRUD、对话编排、工具调用、LLM 客户端构建、用量记录等职责，属典型的上帝类 |
| `backend/app/services/workflow_engine.py` | 666 | 包含 DAG 校验与节点执行 |
| `backend/app/api/agent.py` | 448 | |
| `backend/app/api/knowledge.py` | 367 | |

**建议**：`services/agent.py` 按职责拆分，可参照以下切分（不改变对外接口）：
- `agent_service.py` —— Agent 实体的 CRUD 与校验
- `chat_orchestrator.py` —— 对话编排与 ReAct 循环
- `tool_executor.py` —— 工具/插件调用（当前 `plugin_executor.py` 在 `utils/`，可一并归位）
- `llm_client_factory.py` —— 模型与供应商解析、客户端构建（`agent.py:510-524` 逻辑）

**注意**：拆分属纯结构性重构，**必须**在测试基线建立之后进行，否则无法验证行为等价。

**验收标准**：拆分后单文件均低于 500 行；现有测试全绿；对外 API 与行为无变化。

---

### A2 · 未接入的死代码（P2）

**位置**：`backend/app/models/api_key.py`、`backend/app/core/security.py`（`generate_api_key`）

**事实**：全库检索 `ApiKey` 与 `generate_api_key`，除定义处外**无任何引用**（无 service、无路由、无迁移之外的调用）。而 `docs/api-design.md` §5 声明了 `/api/api-keys` 接口。

**决策建议：删除**，并在文档中划除对应章节。理由：
- 无引用即无现网依赖，删除无回归风险。
- 保留半成品的"API Key 表"会扩大持久化攻击面（若表内曾存密钥）且误导后续开发者。
- 若未来确有第三方接入需求，应从头按 OWASP ASVS 设计（密钥哈希存储而非明文、作用域、吊销、轮换、审计），而非在现有半成品上增量修补。

**验收标准**：文件与函数移除后应用正常启动、测试全绿；文档对应章节已划除或标注"未实现"。

---

## 四、性能与运维

| 项 | 观察 | 建议 |
|----|------|------|
| 中间件顺序 | `main.py:53-73` 注册顺序为 CORS → RateLimit → Tenant → Audit（注释说明"后注册先执行"） | 顺序合理，可作为一致性基线保留；建议在代码中补测验证而不是依赖注释 |
| 限流开销 | 每次请求 4 条 Redis 命令（`zremrangebyscore`/`zadd`/`zcard`/`expire`），使用 pipeline | 设计合理；建议将 `expire` 改为仅在首次写入时设置，减少写放大 |
| 同步 DB 与异步路由混用 | 各 service 使用同步 `Session`，路由为 `async def` | 同步阻塞会占用事件循环线程。当前规模下可接受，但需明确：若后续并发量上升，应改为线程池执行或迁移异步 ORM |
| 迁移链 | `backend/alembic/versions/` 共 17 个版本，未发现断链 | 建议新增一条冒烟测试：容器启动时 `alembic upgrade head` 必须成功（当前 Dockerfile `CMD` 已包含该步骤） |
| 日志 | `main.py:34-37` 配置了 `logging.basicConfig`，格式统一 | 符合 12-Factor 的 Logs 原则（输出到 stdout）。建议补充请求级 `request_id` 以便跨服务追踪 |

---

## 五、后端问题优先级汇总

| ID | 严重度 | 问题 | 一句话理由 |
|----|--------|------|-----------|
| S1 | P0 | CORS 通配 + 携带凭证 | 配置级漏洞，修复成本极低，风险极高 |
| S2 | P0 | 4 个模块缺权限校验 | 越权写操作，能力已具备仅需接线 |
| S3 | P0 | 租户过滤无强制机制 | 已确证 3 处遗漏且无测试覆盖，演进风险高 |
| S4 | P0 | `prompt_versions` 缺 `tenant_id` | 纵深防御缺失，依赖人工约定 |
| S5 | P0 | 上传校验薄弱且大小配置未生效 | 配置项零引用，实际无上限 |
| C1 | P1 | 25 处裸 `HTTPException` | 契约破裂，前端错误提示失真 |
| C2 | P1 | `code` 语义双重 | 前后端错误分支不可靠 |
| C3 | P1 | 废弃参数 `openapi_prefix` | 升级 FastAPI 将破坏路径约定 |
| A3 | P1 | 工作流无整体超时/重试 | 单任务可长期占用 worker |
| S7 | P1 | 限流可伪造 IP 绕过 + fail-open | 登录暴力破解防护强度不足 |
| A1 | P2 | 1194 行上帝类 | 演进与测试成本高 |
| A2 | P2 | 未接入的死代码 | 建议删除，降低误导与攻击面 |
