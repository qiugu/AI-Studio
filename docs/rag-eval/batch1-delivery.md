# 批次 1 交付报告：环境验证与评测框架

> **文档性质**：交付报告（验收用）。
> **对应计划**：[PLAN.md](./PLAN.md) v2.0 的 Phase 0 与 Phase 1。
> **交付日期**：2026-09-12
> **状态**：待验收

---

## 1. 结论摘要

批次 1 的两项任务均已达成，且在生产环境的真实数据上完成验证：

| 项目 | 结果 |
|------|------|
| 既有测试失效 | 4 项全部修复，套件从 **4 failed / 18 passed** 转为 **137 passed / 1 skipped / 1 xfailed** |
| 检索链路致命缺陷（A1） | 已修复——修复前 Agent 知识库工具与 Workflow 知识库节点的检索**完全不可用** |
| 数据一致性（D9） | 生产数据完成校准：**301 条失效分块 + 301 个残留向量 → 0 / 0** |
| 评测框架 | `app/rag_eval/` 六模块 + CLI + 回归门禁全部就位，离线冒烟通过 |
| 新增测试 | 8 个文件、**117 个用例**，覆盖指标正确性、口径一致性、租户隔离与回归防护 |

**一句话结论**：检索链路已从「部分功能静默失效 + 数据泄漏」恢复为可用且受测试保护的状态，评测框架具备度量后续 Reranker / 混合检索增益的能力。

---

## 2. Phase 0：环境验证与缺陷修复

### 2.1 实测证据（非推断）

三项关键结论均通过在生产环境实际执行获得，而非静态阅读代码得出。

**A2 —— 向量删除机制的失效与修复**

| 写法 | 结果 |
|------|------|
| 旧：`points_selector=<裸字符串>` | 抛 `ValueError: Unsupported points selector type: <class 'str'>`，3 个点**全部残留**；异常被 `except Exception: pass` 吞掉 → 静默失败 |
| 新：`points_selector=PointIdsList(points=[...])` | 一次批量提交，剩余点数 **0** |

**D8 —— `query_points` 与已废弃 `search` 的等价性**

在线上 collection 上以同一向量取 top-10 比对：**排序完全一致（True）、分数完全一致（True）**。这为迁移到 `query_points` 提供了实证依据（后者是 Phase 5 混合检索 prefetch + RRF 所需的 API 形态）。

**D9 —— 已下架文档仍在被检索召回**

诊断发现 `bfcaa9d3` 文档已被软删除，但其 **301 个分块的 `deleted_at` 仍为 NULL**，且 **301 个向量仍在 Qdrant**。由于检索回表的过滤条件正是 `deleted_at IS NULL`，该文档仍在被正常召回——这是一次真实的**已下架内容泄漏**。

叠加影响：该文档与 `4626a81d` 为**同名文件**，因此召回结果中同一段落会出现两遍。

### 2.2 D9 存量数据处置

代码侧修复只能阻止新增泄漏，存量数据需单独校准。为此产出运维工具 `backend/scripts/repair_orphan_vectors.py`（339 行）。

**设计取舍**：刻意做成**可复用的兜底工具**而非一次性脚本——MySQL 与 Qdrant 是两个独立存储，缺乏事务保证，同类不一致必然再次出现。

安全设计：

- **默认只读**，须显式 `--execute` 才写入；
- **幂等**，可重复执行；
- 执行前完整打印待处理清单与数量，便于人工核对；
- 不介入 `knowledge_bases` 的计数维护，避免与业务逻辑重复扣减。

**执行结果**：

```
修复前：失效分块 301 条 | 孤儿向量 0 个 | 本次将删除的向量 301 个
修复后：失效分块   0 条 | 孤儿向量 0 个     ← 数据一致
```

最终数据状态：MySQL 存活分块 301 / 已软删 301，Qdrant 点数 301，已下架文档 `bfcaa9d3` 的向量数为 **0**。三项两两自洽。

### 2.3 阻塞项解除

| 编号 | 原阻塞描述 | 结论 |
|------|-----------|------|
| D4 | 复核 MySQL 知识库三表是否已建 | **已解除**：`knowledge_bases` / `knowledge_documents` / `knowledge_chunks` 三表齐备 |
| D6 | API 默认模型与维度映射表不匹配导致建库 500 | **已修复**：建库默认模型改为从配置取值；`get_vector_size_for_model` 补齐 OpenAI 系列映射 |
| D9 | 已下架文档仍被召回 | **已修复并完成存量化校准**（见 2.2） |

---

## 3. Phase 1：评测框架

### 3.1 模块结构

```
backend/app/rag_eval/
├── metrics.py       纯函数指标：Recall / Hit / Precision / RR / AP / DCG / nDCG + 分组聚合
├── dataset.py       金标准 schema、JSONL 读写、校验、统计
├── retrievers.py    三类检索器 + 口径一致性约束
├── runner.py        编排、单查询打分、宏观聚合、分类型聚合、分阶段延迟
├── report.py        JSON / Markdown 双格式报告 + 回归门禁
└── __init__.py      对外导出
backend/scripts/rag_eval.py            CLI 入口（358 行）
backend/tests/fixtures/rag_eval/       离线冒烟语料与金标准
```

### 3.2 三项方法学约束（不可妥协）

**① 指标分母取完整相关集。** Recall 与 MAP 的分母一律为 `|R|`，而非 `top_k` 截断后的集合。若误用后者，Recall 会被系统性高估——这是检索评测中最常见的口径错误。`tests/test_rag_metrics.py` 与 `test_rag_eval_runner.py` 中有专门用例锁定该口径。

**② 评测口径与线上口径必须同源。** `QdrantRetriever` 强制经由 `app.core.vector_db.search_points()` 完成召回，与业务 `KnowledgeBaseService.search()` 共用同一实现。评测侧一旦另写一份 Qdrant 查询逻辑，评测结论就无法再用于推断线上行为。

**③ 召回损失与排序损失分开度量。** 当检索器提供宽召回候选集时，同时产出 `candidate_recall` 与 `recall@k`，两者差额即纯粹由排序造成的损失。这是判断「该补召回还是该上精排」的唯一依据——只报一个 Recall@k 无法区分「没捞到」与「捞到了但排太后」。

### 3.3 三类检索器

| 实现 | 依赖外部服务 | 用途 |
|------|-------------|------|
| `InMemoryRetriever` | 否 | 单测与 CI。确定性 md5 特征哈希 + IDF 加权，逐位可复现，验证的是**评测框架本身**的正确性 |
| `QdrantRetriever` | 是 | 端到端真实链路，产出可对外引用的指标 |
| `RerankedRetriever` | 取决于被包装者 | 宽召回 + 精排装饰器，用于度量重排增益（Phase 3 接入本地模型时无需改动本类） |

### 3.4 离线冒烟结果

```
运行：smoke    检索器：in-memory-hash
查询数：6（失败 0）
指标        @1        @3        @5       @10
RECALL   0.9167    1.0000    1.0000    1.0000
MRR      1.0000    1.0000    1.0000    1.0000
NDCG     1.0000    0.9866    0.9866    0.9866
MAP      0.9167    0.9722    0.9722    0.9722
召回延迟 p50=0.033ms  p95=0.378ms
```

> 该结果仅证明**框架计算正确**，不构成任何检索质量基线。质量结论须待 Phase 2 用 `mteb/T2Retrieval` 产出。

### 3.5 CLI 用法

```bash
# 离线冒烟（无需任何外部服务）
AI_STUDIO_SKIP_ENV_FILE=1 python scripts/rag_eval.py \
    --retriever in-memory \
    --golden tests/fixtures/rag_eval/golden.jsonl \
    --corpus tests/fixtures/rag_eval/corpus.jsonl \
    --name smoke --out-dir /tmp/reports

# 端到端（真实 Qdrant）
python scripts/rag_eval.py --retriever qdrant --collection kb_<uuid> \
    --golden <golden.jsonl> --name baseline \
    --baseline <baseline.json> --max-drop-pp 1.0     # 回归门禁：Recall@5 下降 ≤1pp
```

退出码：`0` 正常；`1` 回归门禁未通过；`2` 参数或环境错误。

---

## 4. 测试与质量

### 4.1 套件状态

| 指标 | 数值 |
|------|------|
| 收集用例 | 139 |
| 通过 | **137** |
| 跳过 | 1（本地向量化依赖未安装） |
| 预期失败（xfail） | 1（D11 `chunk_overlap` 未生效，计划 Phase 5 修复） |

### 4.2 新增测试明细

| 文件 | 用例数 | 覆盖目标 |
|------|--------|----------|
| `test_rag_metrics.py` | 29 | 5 项指标的手算期望值 + 边界（无相关、k 超界、重复 ID、并列） |
| `test_rag_eval_runner.py` | 24 | 编排、聚合、回归门禁、候选召回口径 |
| `test_rag_eval_dataset.py` | 17 | JSONL 读写、schema 校验、错误行号定位 |
| `test_repository_tenant_isolation.py` | 14 | 租户隔离——**防止 A3 类漏洞回归** |
| `test_rag_eval_cli.py` | 11 | CLI 端到端、回归门禁退出码 |
| `test_text_splitter.py` | 9 | 分块边界（含 D11 的 xfail 标记） |
| `test_knowledge_service_signature.py` | 7 | AST 全量扫描调用点——**防止 A1 类签名漂移回归** |
| `test_knowledge_vector_delete.py` | 6 | 删除入参断言、失败留痕、软删级联 |
| **合计** | **117** | |

两类**防回归**测试值得单独指出：`test_knowledge_service_signature.py` 用 AST 扫描全仓库所有 `search(` 调用点，一旦参数名再次漂移立即失败；`test_repository_tenant_isolation.py` 编译 SQL 断言 `tenant_id` 过滤存在，使租户隔离漏洞无法悄悄回归。

### 4.3 测试基础设施修复

**问题**：`app.core.config` 在导入期读取 `backend/.env`，导致任何缺少真实凭据的环境（含 CI）在 collection 阶段即整体失败——**测试无法运行**。

**修复**：引入 `AI_STUDIO_SKIP_ENV_FILE` 开关（默认行为不变），并提供 `backend/conftest.py` 与 `pytest.ini` 注入测试默认值。测试环境不再依赖本机凭据文件。

---

## 5. 代码审查

按约定执行三维度审查。

### 5.1 可读性与注释

**结论：良好。** 关键设计决策均以「为什么」而非「是什么」注释，例如：

- `metrics.py` 模块头明确两条不可妥协的口径约束及其后果；
- `retrievers.py` 用表格区分三类实现的适用场景，并标注「不可互相替代」；
- `delete_document` 注明「顺序不可调整」及调整后的具体后果；
- `repair_orphan_vectors.points_to_purge()` 说明为何不能用 `orphan_points` 代替。

### 5.2 性能与安全

**已修复的问题**：

| 问题 | 性质 | 处置 |
|------|------|------|
| 检索回表 N+1 | 性能 | 改为批量 `IN` 查询 + `joinedload` 预加载 |
| `get_by_vector_id` 缺 `tenant_id` 过滤 | **安全（多租户隔离漏洞）** | 补全过滤条件 |
| `delete_document` 裸写 `db.query` | 规范/安全 | 改走 Repository |
| 向量删除异常被静默吞掉 | 可观测性 | 改为记录 warning 日志并保留上下文 |

**新代码的性能特征**：`InMemoryRetriever` 使用矩阵乘（`self._vectors @ query_vector`）而非逐条循环；`list_by_vector_ids` 空列表提前返回，避免无效 SQL。

### 5.3 项目规范遵循

- **多租户隔离**：所有数据访问经 `BaseRepository`，测试中有 SQL 级断言锁定；
- **异常体系**：业务层沿用项目自定义异常；评测层为纯函数模块，使用标准 `ValueError` / `TypeError`；
- **解耦要求**：评测层仅依赖 `app.core.vector_db.search_points` 一处业务实现，不触碰 MySQL，符合「可离线运行」的设计约束。

### 5.4 遗留改进项（不在本批次范围）

1. **`datetime.utcnow()` 弃用警告**：项目中多处使用，Python 3.12+ 提示迁移至 `datetime.now(datetime.UTC)`。因涉及面广且与现有风格一致性相关，建议独立立项统一迁移，避免本批次混入广泛改动。
2. **pytest `--basetemp` 并发争用**：沙箱下系统临时目录不可写，须用 `--basetemp=.pytest-tmp`；若并发启动多个 pytest 进程会因争用该目录出现 setup 错误（本次测量中曾复现 13 个 ERROR，串行重跑即全绿）。建议在 CI 配置中固定为串行或为各进程分配独立 `basetemp`。

---

## 6. 遗留问题与下一批次

### 6.1 本批次未覆盖（按计划顺延）

| 编号 | 内容 | 归属 |
|------|------|------|
| D11 | `TextSplitter._merge_splits` 从未把 `chunk_overlap` 纳入计算，声明的 128 字符重叠实际为 0 | Phase 5 |
| D8 | 迁移至 `query_points`（等价性已验证，业务侧已切换） | 已完成 |
| A6 | PDF OCR / 版面还原 | 已排除，建议单独立项 |
| 分块元数据 | `heading_path` / 页码回填 | Phase 5 |

### 6.2 下一批次（批次 2 = Phase 2 + 3 + 4）

1. **Phase 2**：采样 `mteb/T2Retrieval`（seed=42，2 万段落 + 100 query），含**分块切断检测**——若 ground truth 段落被分块器切断，任何单块都无法独立支撑答案，会人为压低 Recall 上限；
2. **Phase 3**：接入本地 `bge-reranker-v2-m3`（本机已缓存 2.1 GB，离线可用），仅集成到 `search()`；
3. **Phase 4**：基线 vs Reranker 对照实测，产出可对外引用的质量与延迟结论。

**需注意的环境前提**：Phase 2 采样依赖 `datasets` 库与 HuggingFace 访问；若需内网离线，须提前确认 `HF_ENDPOINT` 镜像配置。

---

## 7. 交付物清单

**新增代码**

| 路径 | 行数 | 说明 |
|------|------|------|
| `backend/app/rag_eval/metrics.py` | 200 | 检索质量指标 |
| `backend/app/rag_eval/dataset.py` | 254 | 金标准集 schema 与 IO |
| `backend/app/rag_eval/retrievers.py` | 322 | 三类检索器 |
| `backend/app/rag_eval/runner.py` | 271 | 编排与聚合 |
| `backend/app/rag_eval/report.py` | 310 | 报告与回归门禁 |
| `backend/app/rag_eval/__init__.py` | 79 | 模块导出 |
| `backend/scripts/rag_eval.py` | 358 | 评测 CLI |
| `backend/scripts/repair_orphan_vectors.py` | 339 | 一致性校准工具 |
| `backend/conftest.py` + `pytest.ini` | — | 测试基础设施 |

**新增测试**：8 个文件、117 个用例（明细见 4.2），另含 `tests/fixtures/rag_eval/` 离线语料。

**修改文件**：`core/config.py`、`core/vector_db.py`、`core/celery_app.py`、`services/knowledge.py`、`services/agent.py`、`services/workflow_engine.py`、`repositories/knowledge.py`、`api/knowledge.py`、`utils/embedding.py`、`AGENTS.md`、`requirements.txt`、`docker-compose.yml`、`Dockerfile`、`.gitignore`，以及既有测试 `test_embedding.py`、`test_vector_db.py`。

**生产数据变更**：Qdrant collection `kb_e5dd6706…` 向量数 602 → 301；MySQL `knowledge_chunks` 软删 301 条（均为已下架文档 `bfcaa9d3` 的分块）。

---

## 8. 验收要点

请重点确认以下三项：

1. **生产数据变更是否认可**：D9 校准删除了 301 个向量，均属已下架文档，业务上不应被检索；原文件仍在 `UPLOAD_DIR`，如需恢复可重新索引。
2. **评测口径是否符合预期**：指标分母用完整相关集、评测与线上共用 `search_points`、召回损失与排序损失分开度量——这三条决定了后续所有质量结论的可信度。
3. **是否同意进入批次 2**：Phase 2 需要 HuggingFace 数据访问；若为内网环境，需先确认镜像方案。
