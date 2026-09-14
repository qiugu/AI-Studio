# 03 · 工程设施评审（质量工具 / 测试 / CI / 容器 / 仓库卫生）

> 范围：代码质量工具链、测试基线、CI/CD、容器与编排、依赖管理、仓库与凭据卫生

---

## 结论

项目的**部署编排质量高于其质量保障体系**：`docker-compose.yml` 已为 MySQL / Redis / Qdrant / 后端 / 前端配置健康检查与 `service_healthy` 依赖顺序，卷持久化与网络隔离齐备，Nginx 已针对 SSE 正确关闭缓冲。

短板集中在"没有门禁"：

- 后端**无任何** lint / 格式化 / 类型检查配置；
- 前后端**均无 CI**；
- 前端**零测试**，后端测试无覆盖率度量且**未覆盖 API、Service、中间件、鉴权**四类核心路径；
- 更深层的问题是：**测试套件本身、`AGENTS.md`、以及大部分 `docs/` 都还未纳入版本控制** —— 这意味着当前仓库对协作者而言并非可用状态。

另有一项需立即处理的高危卫生问题（见 §1）。

---

## 一、仓库卫生与凭据安全

### H1 · 存在未被忽略的 `.env` 备份文件，且会被打入镜像（P0）

**位置**：`backend/.env.bak-20260912`

**事实与证据**：

1. 该文件存在于工作区，且 `git status` 中为 **untracked（`??`）** 状态。
2. **不被任何 `.gitignore` 规则覆盖** —— `git check-ignore -v backend/.env.bak-20260912` 无输出。根 `.gitignore` 仅包含 `.env`（精确匹配），无法匹配 `.env.bak-20260912`。
3. 因此一次常规的 `git add -A && git commit` 就会把该文件提交进版本库。
4. **同时**：`backend/.dockerignore`（内容为 `.venv` / `__pycache__` / `*.pyc` / `.env` / `.pytest_cache` / `.mypy_cache` / `.ruff_cache` / `*.log`）中**同样没有** `.env.bak-20260912`，而 `backend/Dockerfile` 使用 `COPY . .`，因此该文件会被复制进镜像层，成为分层缓存中长期残留的敏感数据。

**关于内容的说明**：本次评审**未能读取**该文件内容（受本机安全策略拦截）。但从命名（`.env` 备份）与用途判断，其中极可能包含真实的数据库口令、`JWT_SECRET_KEY` 与 `FERNET_KEY`。无论内容如何，它都不应处于"可被一条 `git add -A` 纳入"的状态 —— 这个判定不依赖内容即可成立。

**改进建议（按顺序执行）**：
1. **确认并删除本地文件**（若确无保留必要），或移至版本库与构建上下文之外的位置。
2. `.gitignore` 补充通配规则：`.env` 改为 `.env*`，或增加 `.env.*` 与 `*.bak*`。
3. `backend/.dockerignore` 同步增加 `.env*` 与 `*.bak*`。
4. **无论是否保留文件，都应评估密钥轮换**：如果该文件曾以任何形式离开过本机（备份、同步盘、镜像推送），则 `JWT_SECRET_KEY` 与 `FERNET_KEY` 必须轮换 —— 后者尤其关键，因为 `FERNET_KEY` 用于解密已存储的供应商 API Key，轮换需配套数据重加密方案。
5. 引入 `pre-commit` 钩子与 `gitleaks` / `detect-secrets` 类扫描，防止同类问题复发。

**验收标准**：`git status --short` 中不再出现任何 `.env*` 文件；`git check-ignore backend/.env.bak-20260912` 有命中；秘密扫描工具在提交时能拦截含密钥的文件。

---

### H2 · 关键资产未纳入版本控制（P1）

**位置**：`git status` 中的 untracked 项（合计 51 项变更，其中 18 项 modified、33 项 untracked）

**未跟踪但属于项目必需资产的条目**：

| 条目 | 性质 | 影响 |
|------|------|------|
| `AGENTS.md` | 技术架构与开发指南（11.7 KB） | **新人 clone 后完全拿不到**，而 `README.md` 明确指向它；`CLAUDE.md` 亦为已跟踪状态，二者不对称 |
| `backend/tests/` 下 17 项（含 14 个测试文件、`fixtures/`） | 测试套件主体 | 团队其他成员无法运行同一套测试 |
| `backend/conftest.py`、`backend/pytest.ini` | 测试配置 | 同上；缺少 `conftest.py` 时测试会因读取 `.env` 失败而在 collection 阶段中断 |
| `backend/app/rag_eval/`（8 个模块）、`backend/app/utils/reranker.py` | 生产代码 | **生产代码未入库** |
| `backend/scripts/` 下 4 个脚本 | 数据准备与修复脚本 | 评测集无法复现 |
| `docs/assets/`、`docs/rag-eval/`、`docs/knowledge-base-enhancement-assessment.md`、`docs/plan-*.md` | 文档与截图 | 文档体系不完整（`README.md` 引用的截图路径即在此目录） |
| `backend/data/` | 评测数据集（`.gitignore` 已刻意保留金标准文件入库，但目录本身仍未跟踪） | 与 `.gitignore` 中的注释意图**自相矛盾** |

**特别注意最后一项**：根 `.gitignore` 中有一段明确注释说明"金标准（`golden.jsonl` / `manifest.json`）体积小且是人工审阅对象，**故保留入库**"，但整个 `backend/data/` 目录实际上处于未跟踪状态 —— **`.gitignore` 的设计意图与仓库实际状态不一致**。这说明忽略规则是按"应当如何"编写的，而提交行为没有跟上。

**改进建议**：
1. 分批提交：先提交生产代码与测试（`app/rag_eval/`、`utils/reranker.py`、`tests/`、`conftest.py`、`pytest.ini`、`scripts/`），再提交文档，最后处理数据文件。
2. 提交前先完成 H1（避免密钥被一并带入）。
3. 建立"提交前检查 `git status`"的习惯，或由 CI 告警"存在未跟踪的 `*.py` 生产文件"。

**验收标准**：`git status --short` 中不再出现 `app/**/*.py`、`tests/**`、`*.md` 类未跟踪项。

---

### D5 · 工作区改动未收敛（P1，且为整改前置条件）

**位置**：`git status`（51 项变更）

**已修改但未提交的文件**中，包含本次整改的核心目标文件：

- `backend/app/api/knowledge.py`（C1 的 13 处 `HTTPException` 在此）
- `backend/app/services/agent.py`（A1 的 1194 行上帝类）
- `backend/app/services/knowledge.py`、`backend/app/services/workflow_engine.py`（A3）
- `backend/app/core/config.py`（S1、S5 需新增配置项）
- `backend/requirements.txt`、`docker-compose.yml`、`backend/Dockerfile`

**为什么这是硬前置条件**：S3 计划改造 49 处数据访问、C1 计划改造 25 处异常抛出，均落在上述未提交文件上。在不干净的工作区上做结构性改造，会使新改动与既有未提交内容混杂 —— 一旦需要回滚，无法精确分离"我改的"与"原本就没提交的"。

**建议**：作为整改的第 0 步，先把现有改动整理为若干语义清晰的提交（可参考仓库已有的 Conventional Commits 风格，见 `.trae/rules/git-commit-message.md`）。

---

### D4 · 根 `.gitignore` 覆盖不全（P2）

**位置**：`.gitignore`（根目录）

**当前内容**：`.venv/`、`__pycache__/`、`.env`、`.hf-cache/`、`backend/.pytest-tmp/`、`backend/data/rag_eval/reports/`、`backend/data/rag_eval/{corpus,chunks,index_manifest}`。

**缺口**：

| 缺口 | 说明 |
|------|------|
| `node_modules/`、`dist/` | 仅由 `frontend/.gitignore` 覆盖。根级规则缺失使得在根目录执行批量操作时保护不完整 |
| `.env.*` / `*.bak*` | 直接导致 H1 |
| `.DS_Store` | 仅 `frontend/.gitignore` 覆盖；macOS 环境下根目录与 `docs/` 会持续产生该文件 |
| `backend/.pytest-tmp/` 之外 | 若在根目录运行 pytest，`.pytest-tmp` 不在忽略范围 |

**正面发现**：`.hf-cache/` 的忽略带有明确注释（约 3 GB，可由脚本重新下载），说明忽略规则经过了思考，问题只在覆盖度。

**建议**：合并为一份根级权威 `.gitignore`，`frontend/.gitignore` 仅保留前端特有项；或保留两份但在根级补齐上述通配规则。

---

## 二、代码质量工具

### E1 · 后端无 lint / 格式化 / 类型检查（P2）

**事实**：`backend/` 下不存在 `pyproject.toml`、`setup.cfg`、`.flake8`、`ruff.toml`、`mypy.ini` 中的任何一项；`requirements.txt` 中无 `ruff`、`black`、`mypy` 相关的直接依赖。

**有趣的对照**：`backend/.dockerignore:6-7` 已列出 `.mypy_cache` 与 `.ruff_cache` —— 说明这些工具曾被纳入规划或短时使用过，但配置文件并未保留。

**影响**：这是 S3（49 处裸 `db.query`）与 C1（25 处裸 `HTTPException`）能够长期存在的**根本原因之一** —— 违反约定的代码没有任何自动化手段能发现。仅靠人工评审无法在 13,187 行代码上维持约定。

**改进建议**：
1. 引入 `ruff`（同时承担 lint 与格式化，替代 black + flake8 + isort，速度快），配置写入 `backend/pyproject.toml`。
2. 建议启用规则集：`E`/`F`/`W`（基础）、`I`（import 排序）、`B`（bugbear）、`UP`（pyupgrade）、`S`（bandit 安全检查，对 `except:` 裸捕获与 `subprocess` 有直接价值）、`ASYNC`（异步误用）。
3. 分阶段引入 `mypy`：先 `--ignore-missing-imports` 且仅对 `app/core`、`app/repositories` 生效，再逐步扩大。
4. 特别建议配置**自定义规则**禁止裸 `except:`，以及用 CI 脚本检查 `services/` 下裸 `db.query`（对应 S3 的"机制强制"）。
5. 在 `pytest.ini` 同目录的 `pyproject.toml` 中集中管理 pytest 与 ruff 配置，减少配置文件碎片。

**验收标准**：`ruff check backend/app` 零告警；`ruff format --check` 通过；CI 中二者为阻断项；`pyproject.toml` 存在且规则集有注释说明取舍原因。

---

### E6 · 前端并存两套 ESLint 配置，其中一套已失效（P2）

**位置**：`frontend/eslint.config.js`（flat config，ESLint 10 使用）+ `frontend/.eslintrc.cjs`（legacy）

**问题**：

| 项 | flat config | legacy config |
|----|-------------|---------------|
| 文件 | `eslint.config.js` | `.eslintrc.cjs` |
| 是否生效 | **生效**（ESLint 10 默认使用 flat） | **不生效**，属死配置 |
| 依赖完整性 | `typescript-eslint`、`@eslint/js`、`globals`、`eslint-plugin-react-hooks`、`eslint-plugin-react-refresh` 均已在 devDependencies | 引用了 `plugin:react/recommended`（需 `eslint-plugin-react`）与 `@typescript-eslint/parser`／`eslint-plugin-@typescript-eslint`，**这些包均未安装** |
| 规则取舍 | 继承 `tseslint.configs.recommended` | 显式关闭 `@typescript-eslint/no-explicit-any`，将 `no-unused-vars` 降为 warn |

**影响**：死配置会被误认为"项目也检查了 React 相关规则"，实际上 `plugin:react/recommended` 从未执行过（且若有人尝试启用会因缺少依赖而报错）。

**改进建议**：
1. 删除 `.eslintrc.cjs`。
2. 若要补足 React 规则，在 `eslint.config.js` 中安装并启用 `eslint-plugin-react` 与 `eslint-plugin-react-hooks`（后者已配置）。
3. 评估是否收紧 `@typescript-eslint/no-explicit-any` —— 当前全库约 15 处显式 `any`，从 `off`/`warn` 提升至 `error` 的成本很低，可防止其增长。
4. 保留 `frontend/.prettierrc` 与 ESLint 的职责边界（格式化归 Prettier，质量归 ESLint），避免规则重叠。

**验收标准**：`npx eslint .` 仅加载一份配置；`npm run lint` 零错误；`no-explicit-any` 为 `warn` 或 `error`。

---

## 三、测试基线

### E3 · 后端测试覆盖面窄且无覆盖率度量（P2）

**现状**：`backend/tests/` 共 19 个测试文件（其中 **14 个未纳入 git**，见 H2）。

**已有覆盖（值得肯定）**：

| 主题 | 文件 |
|------|------|
| RAG 评测 | `test_rag_eval_cli.py`、`test_rag_eval_dataset.py`、`test_rag_eval_runner.py`、`test_rag_metrics.py`、`test_rag_passage_mapping.py` |
| 向量与检索 | `test_vector_db.py`、`test_vector_db_collection.py`、`test_embedding.py`、`test_embedding_client.py`、`test_reranker.py` |
| 文档处理 | `test_text_splitter.py` |
| 安全基础件 | `test_encryption.py` |
| 数据隔离 | `test_repository_tenant_isolation.py` |
| 任务与签名 | `test_celery_config.py`、`test_celery_task_registration.py`、`test_knowledge_service_signature.py`、`test_knowledge_search_rerank.py`、`test_knowledge_vector_delete.py` |

测试基础设施的质量也值得肯定：`backend/conftest.py` 做了两件正确的事 —— 通过 `AI_STUDIO_SKIP_ENV_FILE=1` 让测试不依赖本机 `.env`（`core/config.py:14-20` 为此专门设计了开关），并通过 `NO_PROXY` 排除 `127.0.0.1`/`localhost` 以避免本机全局代理导致的 502 误判。`pytest.ini` 定义了 `integration` 与 `slow` 两个 marker 并声明"服务不可达时自动 skip"。这些都是有经验的做法。

**缺口（按重要性排序）**：

| 缺口 | 风险 |
|------|------|
| **无 API 路由测试** | C1（25 处 `HTTPException`）、C2（`code` 语义）无任何回归保护；统一响应契约无法验证 |
| **无 Service 业务逻辑测试** | S2（权限）、S3（租户过滤遗漏）核心路径无覆盖 |
| **无中间件测试** | S7（限流）的 IP 伪造与降级行为完全未验证 |
| **无鉴权/权限测试** | 路由守卫是否生效无验证 |
| 无覆盖率度量 | `requirements.txt` 中无 `pytest-cov`（已确认），无法回答"改了多少、测了多少" |

**注意**：`test_repository_tenant_isolation.py` **已经存在**并将被纳入，这是个很好的起点 —— 它证明团队已认识到租户隔离需要测试，只是范围尚未扩展到 service 层（S3 的 3 处遗漏恰在 service 层）。

**改进建议（按优先级）**：
1. 引入 `pytest-cov`，先只度量不设门槛，得到真实基线。
2. 优先补三类测试（成本最低、直接对应已确证问题）：
   - **统一响应契约测试**：遍历所有路由，断言错误响应含 `code`/`message`/`data`（保护 C1、C2）；
   - **跨租户访问测试**：扩展现有 `test_repository_tenant_isolation.py` 到 service 层（保护 S3、S4）；
   - **权限守卫测试**：断言无权限角色访问写接口返回 403（保护 S2）。
3. 覆盖率门槛分阶段设定（例如先 40%，随改造推进提升），且只对 `app/api`、`app/services`、`app/repositories` 计算，避免被 `rag_eval` 稀释。
4. 保留 `integration`/`slow` marker 的现有设计，在 CI 中默认跳过 `integration`。

**验收标准**：`pytest --cov=app` 可输出报告；上述三类测试存在且通过；CI 中覆盖率门槛为阻断项。

---

### E4 · 前端零测试（P2）

**事实**：`frontend/` 下不存在任何 `*.test.*` / `*.spec.*` 文件；`package.json` 中无 `vitest`、`jest`、`@testing-library/react`；`scripts` 中无 `test` 命令。

**影响**。前端当前存在两个已被确认的缺陷（[F1](02-frontend.md) 的 sanitize 缺失、[E9](02-frontend.md) 的刷新队列挂起），二者都属于**可以用极小的单元测试锁死**的类型：

- E9 只需 mock 刷新接口返回失败，断言排队请求进入 `catch`；
- F1 只需渲染含恶意 HTML 的 Markdown，断言输出中不含可执行节点。

没有测试框架意味着这类修复无法被固化，回归风险由人承担。

**改进建议**：
1. 引入 `vitest`（与 Vite 同源，配置成本最低）+ `@testing-library/react` + `jsdom`（或 `happy-dom`）。
2. `package.json` 增加 `"test": "vitest run"` 与 `"test:watch": "vitest"`。
3. 首批测试锁定三个目标（成本低、价值高）：
   - `utils/request.ts` 的刷新失败路径（E9）；
   - `utils/auth.ts` 的令牌读写（S6 改造后的契约）；
   - `MarkdownRenderer` 的 sanitize 行为（F1）。
4. **暂不追求组件快照测试** —— 30+ 页面的快照维护成本高、收益低。优先覆盖纯逻辑模块（`utils/`、`api/`、`hooks/`），这与 Testing Pyramid 的底层优先原则一致。

**验收标准**：`npm run test` 可运行且通过；上述三个测试文件存在；CI 中前端测试为阻断项。

---

## 四、CI/CD

### E2 · 无 CI（P2）

**事实**：项目根目录不存在 `.github/`、`.gitlab-ci.yml`、`Jenkinsfile` 中的任何一项（已确认）。

**影响**：这是本报告所罗列问题的**结构性成因**。E1、E3、E4、E5、E6、H1 若各自单独存在，都属可接受的局部欠缺；但缺少 CI 意味着这些欠缺无法被持续发现与收敛 —— 关闭的 `strict`、缺失的 lint、不存在的测试，会在无人察觉的情况下长期停留。

**建议的 CI 最小集**（GitHub Actions，两个 job 可并行）：

**job 1 · backend**
1. `ruff check backend/app`（E1）
2. `ruff format --check backend`（E1）
3. `pytest --basetemp=.pytest-tmp -m "not integration and not slow"` （E3）
4. `pytest --cov` 门槛校验

**job 2 · frontend**
1. `npm ci`
2. `tsc -b`（E5）
3. `npx eslint .`（E6）
4. `npm run test`（E4）
5. `npm run build`（构建可用性）

**附加门禁（低成本、高价值）**：
- `gitleaks` 密钥扫描（防 H1 复发）；
- 校验"路由 ↔ 权限点"对照完整性（保护 S2）；
- 校验 OpenAPI 与前端类型的一致性（Spectral，保护 C1、[D1](04-docs-and-scripts.md)、[D2](04-docs-and-scripts.md)）；
- 在 CI 中执行 `git status --porcelain` 并告警未跟踪的生产代码文件（防 H2 复发）。

**关于本机环境的注意事项**（来自项目既有约定，CI 配置需遵守）：
- `pytest` 必须使用 `--basetemp=.pytest-tmp`（工作区内），沙箱禁止写入系统临时目录；
- 所有 `localhost` 网络探测需设置 `NO_PROXY=127.0.0.1,localhost`（项目 `conftest.py` 已处理）；
- `pytest` 不可并发运行（多进程争用同一 `--basetemp` 会导致 setup ERROR）。

**验收标准**：PR 触发 CI；上述检查全部为阻断项；在缺少 `.env` 的干净环境中 CI 能通过。

---

## 五、容器与编排

### E8 · 容器加固与编排参数不足（P2）

**已做得好的部分**（先肯定，避免误判为整体不合格）：

| 项 | 位置 | 评价 |
|----|------|------|
| 健康检查齐备 | `docker-compose.yml` | MySQL（`mysqladmin ping`）、Redis（`redis-cli ping`）、Qdrant（`/dev/tcp` + HTTP 探测，注释解释了为何不用 curl）、backend（`curl /health`）、frontend（`wget 127.0.0.1`，注释解释了 IPv6 误判问题）—— 每处都有注释说明取舍，质量高于常见项目 |
| 依赖顺序正确 | `docker-compose.yml` | `backend` 对 mysql/redis/qdrant 使用 `condition: service_healthy` |
| 数据持久化完整 | `docker-compose.yml` | 5 个命名卷（mysql-data / redis-data / qdrant-data / uploads / hf-cache） |
| 网络隔离 | `docker-compose.yml` | 独立 bridge 网络 `ai-studio-net`，仅 qdrant 与 frontend 暴露端口 |
| 构建上下文隔离 | `backend/.dockerignore`、`frontend/.dockerignore` | **已排除 `.env` 与 `.venv`**，未发现密钥进入镜像的路径（前提是 H1 被修复） |
| 前端多阶段构建 | `frontend/Dockerfile` | builder（node:20-alpine）→ runtime（nginx:1.27-alpine），基础镜像 tag 已固定 |
| 依赖层缓存优化 | `backend/Dockerfile`、`frontend/Dockerfile` | 先 `COPY requirements.txt` / `package*.json` 再装依赖，充分利用层缓存 |
| torch CPU 轮子优化 | `backend/Dockerfile` | 使用 `--extra-index-url https://download.pytorch.org/whl/cpu` 避免拉取 CUDA 版大体积包，并附注释说明 |
| 启动即迁移 | `backend/Dockerfile` CMD | `alembic upgrade head && uvicorn ...` |

**缺口**：

| 缺口 | 位置 | 说明与建议 |
|------|------|-----------|
| **容器以 root 运行** | 两个 Dockerfile 均无 `USER` 指令 | 违反最小权限原则。backend 应 `useradd -m appuser` 后 `USER appuser`（注意 `uploads` 卷的属主需一并处理）；frontend 的 nginx 官方镜像已有 `nginx` 用户，可配置 `nginx.conf` 中 `user nginx;` 并以非 root 启动（或用 `nginxinc/nginx-unprivileged`） |
| **无资源限制** | `docker-compose.yml` | 未设置 `mem_limit` / `cpus` / `deploy.resources`。`celery-worker --concurrency=2` 且加载本地 embedding 模型，内存占用可观，无上限时可能拖垮宿主机。建议为每个服务设置明确上限 |
| **无日志轮转** | `docker-compose.yml` | 未配置 `logging` driver 的 `max-size`/`max-file`。默认 json-file 无上限，长期运行会耗尽磁盘。建议统一配置 `"max-size": "10m", "max-file": "3"` |
| **镜像 tag 未完全固定** | `docker-compose.yml` | `qdrant/qdrant:latest` 使用可变标签，同一份 Compose 文件在不同时间会拉起不同版本，破坏可复现性。违反 Semantic Versioning 与不可变交付物原则。应固定为具体版本或 digest。另：`mysql:8.0`、`redis:7-alpine`、`python:3.12-slim`、`node:20-alpine`、`nginx:1.27-alpine` 已固定 minor，属可接受 |
| **celery-worker 依赖未用健康条件** | `docker-compose.yml` | 使用列表形式的 `depends_on: [backend]`，仅保证启动顺序。若 backend 因迁移失败而未就绪，worker 仍会启动并在连接数据库时反复报错。建议改为 `condition: service_healthy` 或直接依赖 mysql/redis 的健康态 |
| **backend 健康检查端点在 Nginx 未暴露** | `frontend/nginx.conf` | Nginx 仅代理 `/api/`、`/docs`、`/redoc`、`/openapi.json`，不包含 `/health`。若未来需要在容器外探活后端，需补充该 location |
| **backend 生产暴露 Swagger 端口** | `docker-compose.yml` | `ports: ${BACKEND_PORT:-8000}:8000` 暴露了 `8000`，Compose 注释已提醒"生产建议删除本段"。建议在文档中明确生产部署应改为不发布该端口，仅经前端 Nginx 访问 |
| **构建上下文偏大** | `backend/.dockerignore` | 未排除 `data/`（含约 10 MB 评测语料）、`tests/`、`scripts/`。虽不影响正确性，但会增大镜像层。建议补充排除项 |
| **`.dockerignore` 未含 `.env.bak-*`** | `backend/.dockerignore` | 与 H1 联动，必须补充 |

**验收标准**：两个镜像的 `docker inspect` 显示非 root 用户；`docker compose config` 中每个服务有资源限制与日志轮转配置；`qdrant` 使用固定版本。

---

## 六、依赖管理

| 项 | 状态 | 说明 |
|----|------|------|
| 后端版本锁定 | **良好** | `requirements.txt` 约 108 行，**全量使用 `==` 精确锁定**（含 `torch==2.6.0+cpu` 与 `sentence-transformers==3.3.1`）。这在生产项目中是正确的做法 |
| 前端版本锁定 | **良好** | `package-lock.json` 已提交；`Dockerfile` 使用 `npm ci`（回退 `npm install`） |
| 缺失的开发依赖 | 缺 | `requirements.txt` 中无 `pytest-cov`、`ruff`、`mypy`。建议区分 `requirements.txt` 与 `requirements-dev.txt`，避免把质量工具装进生产镜像 |
| 依赖安全扫描 | 缺 | 无 `pip-audit` / `npm audit` / Dependabot 配置。建议在 CI 中增加非阻断的安全扫描并定期review |
| 冗余依赖观察 | 待确认 | `requirements.txt` 同时包含 `anthropic` 与 `openai`（经 LangChain 的 `langchain-anthropic`/`langchain-openai` 间接依赖），以及 `dataclasses-json`、`typing-inspect`（多为 `langchain-community` 传递依赖）。属正常传递依赖树，无需处理，但说明 `requirements.txt` 是"pip freeze 全量导出"而非手工维护的最小集 —— 建议在文件头部注释说明其生成方式 |

---

## 七、工程设施问题优先级汇总

| ID | 严重度 | 问题 | 一句话理由 |
|----|--------|------|-----------|
| H1 | **P0** | `.env.bak-*` 未被忽略且会被打入镜像 | 一条 `git add -A` 即造成密钥入库，且需评估密钥轮换 |
| H2 | P1 | `AGENTS.md`、测试套件、部分生产代码与文档未纳入 git | 仓库对协作者不可用，与 `.gitignore` 注释意图自相矛盾 |
| D5 | P1 | 51 项改动未收敛 | 结构性改造的前置条件，否则无法回滚 |
| E2 | P2 | 无 CI | 上述所有问题的结构性成因 |
| E3 | P2 | 后端测试无 API/Service/中间件/鉴权覆盖，无覆盖率 | C1/S2/S3/S7 无回归保护 |
| E1 | P2 | 后端无 lint/格式化/类型检查 | 约定无法自动化强制 |
| E4 | P2 | 前端零测试 | F1/E9 类缺陷无法固化 |
| E8 | P2 | 容器 root 运行、无资源限制与日志轮转、`qdrant:latest` | 运维风险与不可复现构建 |
| E6 | P2 | 前端 ESLint 双配置（一份失效） | 误导性的质量假象 |
| D4 | P2 | 根 `.gitignore` 覆盖不全 | H2 与 H1 的直接成因 |
