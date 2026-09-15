# RAG 检索质量评测 + 本地 Reranker + 混合检索 — 合并执行计划

- 文档版本：**v2.0（合并版，待评审）**
- 日期：2026-09-11
- 统一文档目录：`docs/rag-eval/`
- 范围：`backend/app/services/knowledge.py` 检索链路、`backend/app/utils/`、`backend/app/rag_eval/`（新建）、Qdrant 索引方案

---

## 0. 版本与合并说明

### 0.1 合并来源

| 来源 | 内容 | 处置 |
|------|------|------|
| `docs/rag-eval/PLAN.md` v1.1 | RAG 评测框架设计、指标体系、公开基准采样协议、本地 Reranker 接入 | **作为骨架保留**（方法学更严谨） |
| `docs/plan-knowledge-retrieval-p0-p2.md` | 检索链路缺陷修复（A 系列）、混合检索方案（P2） | **并入本计划**，P2 升格为 Phase 5 |

> `docs/plan-knowledge-retrieval-p0-p2.md` 自此标记为历史文档，内容以本文件为准。

### 0.2 合并时的决策裁决（2026-09-11 确认）

| # | 冲突/决策点 | 裁决结果 |
|---|-------------|----------|
| 1 | 计划归属 | **合并为单一计划**，文档统一置于 `docs/rag-eval/` |
| 2 | 评测数据源 | **公开中文基准**（`mteb/T2Retrieval` 为首选，`mteb/DuRetrieval` 交叉验证），沿用 v1.1 的采样协议与偏差披露要求 |
| 3 | Reranker 模型 | **`BAAI/bge-reranker-v2-m3`**（本机已缓存 2.1 GB，离线可用） |
| 4 | 混合检索 | **纳入**，采用 Qdrant 原生稀疏向量 + 服务端 RRF 融合 |
| 5 | 交付节奏 | **分三批验收**（见 §7.7） |

### 0.3 已完成项（本次会话已实施并通过语法校验）

| ID | 内容 | 文件 |
|----|------|------|
| A1 | `search()` 调用参数名不匹配（`query_text` → `query`）。**修复前 Agent 知识库工具与 Workflow 知识库节点检索功能完全失效**（`TypeError`）。已用 AST 全量校验三处调用点一致 | `services/agent.py`、`services/workflow_engine.py` |
| A2 | 向量删除改用 `PointIdsList` 批量提交 + 记录日志（原传裸字符串导致静默失败，异常被 `except: pass` 吞掉）= 原 D7 | `services/knowledge.py` |
| A3 | `delete_document` 改走 `KnowledgeChunkRepository.list_by_doc_id`（原裸写 `db.query` 违反多租户约定）；**并修复 `get_by_vector_id` 缺失 `tenant_id` 过滤的租户隔离漏洞** | `services/knowledge.py`、`repositories/knowledge.py` |
| A4 | 检索回表改 `list_by_vector_ids` 批量 `IN` + `joinedload`，消除 N+1 = 原 Phase 3 既定任务，已提前完成 | 同上 |
| A5 | `score_threshold` 提升为 `config.retrieval_score_threshold`（默认 0.0，取消召回阶段硬截断） | `core/config.py`、`services/knowledge.py`、`api/knowledge.py` |
| A10 | 类型注解校正（`kb_id: int` / `doc_id: int` → `str`） | `services/knowledge.py` |
| A8 | AGENTS.md 三处 pgvector → Qdrant | `AGENTS.md` |
| D6 | 建库默认模型改为从 config 取值，消除 API 层与维度映射表各写默认值导致的建库 500 | `api/knowledge.py`、`services/knowledge.py` |

**待验证**：A2 的实际删除效果（原为静默失败，需实测确认向量确实被删除，见 Phase 0 的 0.3）。

---

## 1. 结论摘要

1. **当前 RAG 无任何量化评测能力**：不存在指标体系、金标准数据集或评测入口，召回率 / MRR / nDCG 无法从现有产物得出，必须先建设评测能力。
2. **检索链路为单阶段纯稠密检索**：无混合召回、无 reranker、无查询改写。本次已修复若干直接压低召回上限的实现缺陷（§0.3），但**结构性能力缺失（混合召回 + 精排）仍待 Phase 3 / Phase 5 补足**。
3. **环境已就绪**（较 v1.1 附录有重大变化）：Qdrant 已运行且含存量数据；全部容器 healthy；本地 embedding 已切为 `sentence-transformers`（v1.1 的 D1/D2/D5 已不适用）。仅需补齐评测依赖与镜像源配置。
4. **模型权重离线可用**：`BAAI/bge-m3`（4.3 GB）与 `BAAI/bge-reranker-v2-m3`（2.1 GB）已完整缓存于本机 HuggingFace hub，无需联网下载。
5. **网络约束**：`huggingface.co` 不可达，`hf-mirror.com` 与 PyPI 可达；探测 localhost 服务必须加 `--noproxy '*'`（本机配置了 `HTTP_PROXY=127.0.0.1:52416`）。

---

## 2. 当前 RAG 链路基线（审计结论）

### 2.1 写入链路

| 环节 | 实现位置 | 现状 |
|------|----------|------|
| 文档上传 | `api/knowledge.py` | 落盘 + 投递 Celery 任务 |
| 解析/分块 | `knowledge_processor.py` | `DocumentParser` + `TextSplitter()`，**参数已提升为配置项**：`chunk_size=448 / overlap=64`（原先 1024/128 会导致 49.7% 的块被 512 token 窗口静默截断；D11 重叠失效已修） |
| 向量化 | `knowledge_processor.py` | `get_embedding_client(model=kb.embedding_model)`，默认本地 `bge-base-zh-v1.5`（768 维） |
| 入库 | `knowledge_processor.py` | Qdrant `upsert`，`vector_id = uuid5(NS_DNS, f"{doc_id}_{index}")` |
| Payload | `knowledge_processor.py` | 仅 `tenant_id / kb_id / doc_id / chunk_index`（**无标题路径、无页码**） |

### 2.2 检索链路（评测对象）

`KnowledgeBaseService.search()`：

```
query → embedding → Qdrant.search(limit=top_k) → 批量 MySQL 回查 chunk → 返回
```

| 特征 | 修复前 | 修复后（当前） |
|------|--------|----------------|
| 阈值 | 召回阶段硬过滤 `score_threshold=0.5` | 提为配置项，默认 **0.0（不硬截断）** |
| 候选集 | 与最终返回集相同（`limit=top_k`） | 仍相同（**Phase 3 引入 `candidate_k` 宽召回**） |
| 元数据回查 | 循环内逐条查（N+1） | **批量 `IN` + `joinedload`（已修）** |
| 异常处理 | `except: return []`，Qdrant 故障与"无结果"不可区分 | **记录 warning 日志（已修）** |
| 重排序 | 无 | 无（Phase 3） |
| 混合召回 | 无 | 无（Phase 5） |
| 引用粒度 | `source_page` 恒为 `None` | 未变（Phase 5） |

---

## 3. 问题清单（合并后，含最新状态）

| # | 严重度 | 问题 | 状态 |
|---|--------|------|------|
| A1 | **阻塞** | `search()` 调用参数名不匹配致功能失效 | ✅ 已修 |
| A2 / D7 | 中 | 向量删除传裸字符串导致静默失败 | ✅ 已修并实测验证 |
| A3 | 中 | `delete_document` 违反多租户约定；`get_by_vector_id` 缺 `tenant_id` 过滤 | ✅ 已修 |
| A4 | 中 | 检索回表 N+1 | ✅ 已修 |
| A5 | 中 | `score_threshold=0.5` 硬编码且在召回阶段硬截断 | ✅ 已修（默认 0.0） |
| A8 | 低 | AGENTS.md 写 pgvector，实际为 Qdrant | ✅ 已修 |
| A10 | 低 | 类型注解与实现不符 | ✅ 已修 |
| D6 | 高 | 建库默认模型与向量维度表不匹配 → 建库 500 | ✅ 已修 |
| D1 | 阻塞 | `EMBEDDING_API_BASE` 被 `.env` 行内注释污染 | ⚪ 已不适用（provider 已切本地） |
| D2 | 阻塞 | `EMBEDDING_API_KEY` 为空 | ⚪ 已不适用（同上） |
| D5 | 高 | provider 默认值不一致致恒走 siliconflow | ⚪ 已不适用（工厂已改为读 config） |
| **D11** | 高 | `TextSplitter._merge_splits` 未计入 `chunk_overlap`，声明的 128 字符重叠**实际未生效** | ✅ **已修复**（P3-G）：改为标准回溯合并，实测重叠 119~125 字符；并已按 P3-G 结论把 `chunk_size/overlap` 重新标定为 **448/64**（原 1024 触发 512 token 静默截断）。见 [FIX-AND-HYBRID-RETRIEVAL-REPORT.md](./FIX-AND-HYBRID-RETRIEVAL-REPORT.md) §3 |
| **D12** | 中 | `source_page` 恒为 `None`，无标题路径，无法页码级引用 | ⏳ Phase 5 |
| D8 | 中 | `client.search()` 在 qdrant-client 1.14 已废弃（推荐 `query_points`） | ✅ 已完成（实测 top-10 排序与分数均等价） |
| D9 | 中 | 软删文档的向量仍参与召回，依赖回查过滤，属隐式行为 | ✅ 已核实并修复（存量化校准：301 条失效分块 + 301 个残留向量 → 0/0） |
| D10 | 低 | `delete_tenant_vectors` 全量遍历 collection，O(N) | 技术债登记 |
| D4 | 阻塞 | MySQL 知识库三表缺失 | ✅ 已解除：三表齐备（`knowledge_bases` / `knowledge_documents` / `knowledge_chunks`） |

---

## 4. 指标体系定义（评测口径）

采用 BEIR / MTEB / RAGAS 一致口径，支持**分块级**与**文档级**双口径。

| 指标 | 公式 | 说明 |
|------|------|------|
| `Recall@k` | `|R ∩ T_k| / |R|` | 单查询宏观平均；衡量召回上限 |
| `Hit@k` | `1[|R ∩ T_k| > 0]` | 是否至少命中一条 |
| `Precision@k` | `|R ∩ T_k| / k` | 辅助观察噪声比例 |
| `MRR@k` | `1/N Σ 1/rank_first_relevant` | 未命中记 0 |
| `nDCG@k` | `DCG@k / IDCG@k` | 支持分级相关度 `2/1/0` |
| `MAP@k` | `1/N Σ AP@k` | 补充排序质量 |
| `Latency p50/p95` | 召回 + 重排分段计时 | 性能回归基线 |

**关键口径约束**：
- 分母 `|R|` 来自完整相关集，**不得使用 top_k 截断后的集合**，否则 Recall 被高估。
- 召回阶段与重排阶段**分别计算** `Recall@{candidate_k}` 与 `Recall@k`，以区分「召回损失」与「排序损失」——这也是 Phase 5 混合检索的立项依据。
- 相关性以「分块内容能否独立支撑答案」为准，同时记录 `doc_id` 以派生文档级指标。

---

## 5. 目标架构

```
backend/
├── app/
│   ├── rag_eval/                     # 新增：评测层（与业务解耦，可离线运行）
│   │   ├── metrics.py                # recall@k / mrr@k / ndcg@k / hit@k / map@k
│   │   ├── dataset.py                # GoldenSet 加载与校验（Pydantic + JSONL）
│   │   ├── retrievers.py             # Qdrant / InMemory / Reranked 三种实现
│   │   ├── runner.py                 # 编排：金标准 → 召回 → 指标 → 聚合
│   │   └── report.py                 # JSON + Markdown 双格式报告
│   └── utils/
│       ├── reranker.py               # 新增：本地 CrossEncoder 重排器（延迟加载单例）
│       └── sparse.py                 # 新增（Phase 5）：稀疏编码器
├── scripts/
│   └── rag_eval.py                   # 新增：评测 CLI
├── data/rag_eval/                    # 新增：评测资产
│   ├── corpus.jsonl                  # 采样语料
│   ├── golden.jsonl                  # 金标准集
│   └── manifest.json                 # 采样参数与种子（可复现性凭证）
└── tests/
    ├── test_rag_metrics.py
    ├── test_rag_eval_runner.py
    ├── test_reranker.py
    ├── test_knowledge_service_signature.py   # 签名一致性 + AST 扫描（防 A1 回归）
    ├── test_repository_tenant_isolation.py   # 租户隔离
    └── test_text_splitter.py                 # 分块边界与重叠

docs/rag-eval/                        # 统一文档目录
├── PLAN.md                           # 本文件
├── RERANKER-DESIGN.md                # Phase 3 产出
├── HYBRID-RETRIEVAL-DESIGN.md        # Phase 5 产出
├── FIX-AND-HYBRID-RETRIEVAL-REPORT.md # Phase 5 已实施部分的实施报告
├── PHASE5-REBUILD-PLAN.md            # Phase 5 5.4/5.6/5.8 合流重索引方案
└── EVALUATION-REPORT.md              # Phase 4 / Phase 6 产出（before/after 对照）
```

### 5.1 Reranker 设计要点

| 项 | 方案 |
|----|------|
| 模型 | `BAAI/bge-reranker-v2-m3`（本机已缓存 2.1 GB，`local_files_only=True` 离线加载） |
| 推理 | `sentence-transformers` 的 `CrossEncoder`，输出 logits 经 `Sigmoid` 归一到 `[0,1]` |
| 设备 | 自动探测 `mps`（Apple Silicon）→ `cuda` → `cpu`，可配置强制 |
| 接口 | `Reranker` 协议：`rerank(query, candidates, top_n) -> List[(index, score)]`；实现 `LocalBGEReranker` / `NoopReranker` |
| 集成点 | **仅 `KnowledgeBaseService.search()`**；新增 `use_rerank` / `candidate_k` 可选参数，默认行为由配置开关控制，保持向后兼容 |
| 新流程 | 宽召回 `candidate_k`（默认 20，阈值 0.0）→ CrossEncoder 精排 → 截断 `top_k` → 批量回查元数据 |
| 降级 | 加载/推理失败 → `logger.warning` + 回退稠密排序，**任何情况下不得让检索 500** |
| 性能预算 | 实测 CPU/MPS 下 `candidate_k=20`、`max_length=512` 的 p50/p95，写入报告 |

### 5.2 混合检索设计要点（Phase 5）

| 项 | 方案 |
|----|------|
| 稀疏编码 | Qdrant 原生 sparse named vector；中文需预分词后交由 BM25 编码器 |
| 融合 | Qdrant Query API `prefetch` + `fusion=RRF`，服务端单次往返 |
| 依赖 | `fastembed`（含 `onnxruntime`，镜像 +100~200 MB）+ 中文分词组件 |
| 迁移 | Collection 原地扩列（Spike S1 验证）；不可行则双写 `kb_{id}_v2` + 灰度切换 + 回滚脚本 |
| 分块修复 | D11 重叠修复 + D12 元数据（`heading_path`、真实页码），随重索引一并生效 |
| 客户端升级 | D8 一并从 `client.search()` 迁移至 `query_points()` |

---

## 6. 分阶段执行计划

### Phase 0 — 环境与阻塞缺陷修复

| # | 任务 | 交付 | 验收标准 | 状态 |
|---|------|------|----------|------|
| 0.1 | A1–A5 / A8 / A10 / D6 缺陷修复 | 代码 | 语法校验通过；调用点签名一致 | ✅ **已完成** |
| 0.2 | 环境验证：Qdrant / MySQL / Redis 连通、venv、模型缓存 | 验证记录 | 均可访问 | ✅ **已完成**（全部容器 healthy；venv 位于项目根 `.venv`，Python 3.12.13） |
| 0.3 | **实测验证 A2 向量删除确实生效**（D7 核实） | 验证记录 | 删除文档后 Qdrant `count` 相应减少 | ✅ **已完成**（旧写法抛 `ValueError` 且 3 点全残留；新写法删净为 0） |
| 0.4 | 复核 D4：MySQL 知识库三表是否已建 | 验证记录 | 三表可查询 | ✅ **已完成**（三表齐备） |
| 0.5 | 补齐评测依赖（`datasets`、`sentence-transformers`、`torch`）与 `HF_ENDPOINT` 配置 | 依赖 + 配置 | `from sentence_transformers import CrossEncoder` 成功；镜像可 stream 数据集 | ⏳ 顺延至批次 2（Phase 2 采样前完成） |
| 0.6 | 核实 D9（软删文档向量是否仍参与召回） | 结论记录 | 明确行为并决定处置 | ✅ **已完成**（获实证：301 条失效分块仍被召回；代码修复 + 存量校准均完成） |

### Phase 1 — 评测框架（纯代码，离线可测）

> ✅ **本阶段已全部完成**（2026-09-12）。交付物与实测记录见 [batch1-delivery.md](./batch1-delivery.md)。

| # | 任务 | 交付 | 验收标准 | 状态 |
|---|------|------|----------|------|
| 1.1 | `metrics.py`：5 指标 + 边界处理（无相关、k 超界、并列、重复 id） | 代码 | 单测覆盖手算期望值 | ✅ 已完成（29 用例） |
| 1.2 | `dataset.py`：`golden.jsonl` schema 定义、校验、统计 | 代码 | 非法标注（负相关度、空 query）被拒绝 | ✅ 已完成（17 用例） |
| 1.3 | `retrievers.py`：`QdrantRetriever` / `InMemoryRetriever` / `RerankedRetriever` | 代码 | `InMemoryRetriever` 用确定性哈希向量，结果可复现 | ✅ 已完成 |
| 1.4 | `runner.py` + `report.py` + CLI `scripts/rag_eval.py` | 代码 + CLI | `--help` 可用；输出 JSON + Markdown | ✅ 已完成（11 用例） |
| 1.5 | 单测：`test_rag_metrics.py`、`test_rag_eval_runner.py` | 测试 | `pytest -q` 全绿 | ✅ 已完成（套件 137 passed） |
| 1.6 | 回归门禁：基线指标固化为 JSON 快照 | 门禁 | 断言 `Recall@5` 下降 ≤ 1pp | ✅ 已完成（24 用例） |
| 1.7 | **口径一致性**：`QdrantRetriever` 与业务 `search()` 共用同一检索函数 | 代码 | 评测口径与线上口径不分叉 | ✅ 已完成（抽出 `core/vector_db.search_points` 为唯一入口） |

### Phase 2 — 公开中文基准采样

**已探明的候选基准**（镜像源实测可获取，均非 gated）

| 数据集 | 状态 | 特点 |
|--------|------|------|
| `mteb/T2Retrieval` | 可访问 | 中文长文检索，**首选** |
| `mteb/DuRetrieval` | 可访问 | 中文多文档 QA 检索，**次选/交叉验证** |
| `mteb/MMarcoRetrieval` | 可访问 | MS MARCO 中文翻译版，可选 |
| `mteb/T2Ranking` | 401 | 需授权，**放弃** |

| # | 任务 | 交付 | 验收标准 |
|---|------|------|----------|
| 2.1 | 安装 `datasets` 并配置 `HF_ENDPOINT=https://hf-mirror.com` | 依赖 + 环境变量 | 能 stream 到 `mteb/T2Retrieval` 首条记录 |
| 2.2 | **语料 reservoir 采样**：固定种子（`seed=42`）抽 `M=20000` 段落 | `data/rag_eval/corpus.jsonl` | 条数 = 20000；种子与参数记录于 `manifest.json` |
| 2.3 | **查询筛选**：仅保留「全部相关段落均落在采样语料内」的查询，取前 `Q=100` 条 | `data/rag_eval/golden.jsonl` | 满足条件的查询 ≥ 100 条 |
| 2.4 | 语料入库：走真实 `TextSplitter` + embedding + Qdrant 链路 | collection + chunk 记录 | `kb.chunk_count` 与预期一致；抽样核对向量已写入 |
| 2.5 | 标注口径映射：基准二值 qrels → `rel ∈ {0,1}` | schema 说明 | 报告中明确声明 nDCG 使用二值增益 |
| 2.6 | **分块切断检测**：检验相关段落是否被分块边界切断 | 检测报告 | 受影响查询被剔除或标注，避免人为压低 Recall 天花板 |

> ✅ **本阶段已完成**（2026-09-12）。产物：`manifest.json`（seed=42、M=20000、
> pool=118256、采样比 16.9%）、`corpus.jsonl`（20000 段）、`golden.jsonl`（100 查询 /
> 123 相关段落）、`chunks.jsonl`（28771 分块）、`cut_report.json`。索引经真实
> `TextSplitter` + embedding 链路写入 Qdrant `kb_rageval_t2r`，实测点数 28771，
> 与 `chunks.jsonl` 一致。
>
> **2.6 结论修正**：不采用原方案「剔除受影响查询」。相关段落被切开时，评测改为用
> `chunks.jsonl` 把命中分块**映射回段落**并在段落粒度打分，因此切断不会人为压低
> Recall 上限；`cut_report.json` 的用途转为**披露信号稀释程度**——被切开的段落，
> 其单个分块只承载部分语义，匹配质量客观下降，这属于被评测系统的真实行为，应被
> 观测而非从数据集里隐藏。实测：4195/20000 段落被切分；相关段落中 24/123（19.5%）
> 被切分，影响 23/100 查询。

**采样偏差（必须披露）**：语料为 2 万段落子集，绝对 Recall 会高于全量场景。故主结论限定为「基线 vs 增强」的**相对增益**，而非绝对水平——与工业界 pooled-subsample 做法一致。

### Phase 3 — 本地 Reranker 接入

| # | 任务 | 交付 | 验收标准 |
|---|------|------|----------|
| 3.1 | `app/utils/reranker.py` + 配置项（开关/模型/候选数/batch/设备/max_length） | 代码 + `RERANKER-DESIGN.md` | 离线加载成功；失败自动降级 |
| 3.2 | 集成 `search()`，补 `use_rerank` / `candidate_k` | 代码 | 默认开关关闭时行为与原逻辑等价 |
| 3.3 | 单测 + 慢速集成测试 | 测试 | 注入式 FakeEncoder 单测全绿；真实模型 slow 测试通过 |
| 3.4 | 延迟实测（CPU 与 MPS 各一组） | 测量记录 | p50/p95 写入报告 |

> ✅ **本阶段已完成**（2026-09-12）。`app/utils/reranker.py`（懒加载、失败记忆、
> 可注入 encoder、稳定排序、NaN 兜底）与 `search()` 集成（`use_rerank` /
> `candidate_k`，关闭时与改造前严格等价）均已落地；设计与实测记录见
> [RERANKER-DESIGN.md](./RERANKER-DESIGN.md) v1.1。
>
> **延迟实测**（batch=32、max_length=512、真实分块文本）：CPU **1.59 对/秒**、
> MPS **2.69 对/秒**；batch 扫描显示 **32 为最优**（64 → 2.34、128 → 1.49 对/秒）。
> 换算到单查询：`candidate_k=20` 时 MPS 约 7.4 s、CPU 约 12.6 s；`candidate_k=100`
> 时 MPS 约 37.2 s、CPU 约 62.9 s。
>
> **结论（重要）**：精排在本机硬件上**不具备交互式可用性**，`reranker_enabled`
> 保持默认 `False` 是正确决策。相关风险与处置见 RERANKER-DESIGN.md §6.2。

### Phase 4 — 对照实测与报告

| # | 任务 | 交付 | 验收标准 |
|---|------|------|----------|
| 4.1 | 基线实测：纯稠密，`k ∈ {1,3,5,10}` | 指标 JSON | Recall/MRR/nDCG/Hit/MAP + 延迟 |
| 4.2 | 接入后实测：宽召回 + reranker，同口径 | 指标 JSON | 可与基线逐项对比 |
| 4.3 | 消融与调参：`candidate_k`、`score_threshold`、`top_k` 网格 | 对比表 | 给出推荐配置及依据 |
| 4.4 | 撰写报告 | `EVALUATION-REPORT.md` | 含 before/after 对照、失败案例分析、结论 |

### Phase 5 — 混合检索与分块质量修复（新增）

| # | 任务 | 交付 | 验收标准 |
|---|------|------|----------|
| 5.1 | **Spike S1**：Qdrant 1.14 能否在已有 collection 原地添加 sparse vector 配置 | 结论记录 | 明确迁移路径（原地扩列 or 双写重建） |
| 5.2 | **Spike S2**：中文 BM25 分词方案（预分词 + BM25 编码器 vs 自实现） | 结论记录 | 在编号/专名类 query 上有可测提升 |
| 5.3 | `utils/sparse.py` + Collection schema 扩展 | 代码 | 稀疏向量可写入并检索 |
| 5.4 | 索引管线改造：稀疏编码 + 元数据写入（`heading_path`、真实页码） | 代码 | payload 含新字段 |
| 5.5 | **D11 分块重叠修复** + 单测断言相邻 chunk 重叠长度 | 代码 + 测试 | 重叠长度符合 `chunk_overlap` 配置 |
| 5.6 | Alembic 迁移：`knowledge_chunks.heading_path` | 迁移脚本 | `alembic upgrade head` 成功 |
| 5.7 | `search()` 混合召回 + RRF 融合（与 Phase 3 Reranker 串联） | 代码 | 融合顺序正确；开关可关闭 |
| 5.8 | 全量重索引（双写 + 灰度 + 回滚脚本） | 迁移执行 | v2 与 MySQL chunk 数一致；回滚脚本可用 |
| 5.9 | D8 迁移 `client.search()` → `query_points()` | 代码 | 无弃用告警 |
| 5.10 | 混合检索对照实测（同 Phase 4 口径） | 指标 JSON | 与 Phase 4 结果可逐项对比 |

> **前置校验**：5.8 执行前须校验 `UPLOAD_DIR` 内原文件在位率，缺失项需提示用户重新上传。
> **已实测（2026-09-15）：1/1 在位** ✓（`Happy-LLM-0727.pdf`，19.76 MB，md5 `d1a4820c…`）。

> ### Phase 5 完成状态（2026-09-15 更新）
>
> 详见 [FIX-AND-HYBRID-RETRIEVAL-REPORT.md](./FIX-AND-HYBRID-RETRIEVAL-REPORT.md)（已实施部分）
> 与 [PHASE5-REBUILD-PLAN.md](./PHASE5-REBUILD-PLAN.md)（5.4 / 5.6 / 5.8 的合流重索引方案）。
>
> | # | 状态 | 说明 |
> |---|------|------|
> | 5.1 | ✅ 完成 | **结论：不能原地扩列**，Qdrant 拒绝向匿名稠密集合追加稀疏向量 → 必须新建/回填 |
> | 5.2 | ✅ 完成 | **结论：自实现无状态 BM25**（ASCII 词 + 中文单字 + 二字组 + CRC32 稳定索引），无需 `jieba`/`fastembed`，不增镜像体积 |
> | 5.3 | ✅ 完成 | `app/utils/sparse.py` + 集合 schema 扩展（命名稠密 `dense` + 命名稀疏 `text`） |
> | 5.4 | ✅ 完成 | 元数据已落位：`parse_segments`/`split_segments` 段内切分，`source_page`/`heading_path` 入库并在 `search()` 返回；迁移 `i3j4k5l6m7n8` 已执行。见 [PHASE5-REBUILD-PLAN.md](./PHASE5-REBUILD-PLAN.md) §2 |
> | 5.5 | ✅ 完成 | D11 重叠修复（实测重叠 119~125 字符）+ 分块参数重新标定为 **448/64**（原 1024 触发 512 token 静默截断） |
> | 5.6 | ✅ 完成 | 迁移已执行并三项验证：`heading_path` / `chunk_epoch` / `active_chunk_epoch` / `active_collection`，并**取消分块软删**（删 `deleted_at`，905 墓碑先行物理清除）。见方案 §3 |
> | 5.7 | ✅ 完成 | `search()` 混合召回已实施。**融合方式经实测改为应用层 min-max 加权（α=0.7），不用服务端等权 RRF**（等权 RRF 实测 MRR@10 −7.33pp） |
> | 5.8 | 🔄 执行中 | 业务库重建 + cutover **已完成**（635 块，v2 集合，计数一致，回滚可用）；评测语料重建后台运行中（实测 ≈21h，编排入口 `run_phase5_eval_rebuild.py`）。见方案 §4 |
> | 5.9 | ✅ 完成 | D8：`client.search()` → `query_points()` |
> | 5.10 | ✅ 完成 | 对照实测见报告 §2.3（α ∈ {0.6,0.7,0.8} 三点均不劣于同集合稠密对照）；新分块下的复测并入方案 §4.4（进行中） |

### Phase 6 — 测试、审查与交付

| # | 任务 | 验收标准 |
|---|------|----------|
| 6.1 | 全量单测 `pytest -q` | 全绿，无跳过的关键用例 |
| 6.2 | **代码审查三问**：可读性/注释、性能与安全、是否符合项目风格（分层、BaseRepository、统一响应、`app/` 约定） | 审查记录写入报告附录 |
| 6.3 | 回归门禁复核 | `Recall@5` 下降 ≤ 1pp |
| 6.4 | 文档同步 | 更新 `AGENTS.md`、`docs/core-mechanisms.md`；产出 `EVALUATION-REPORT.md` 终稿 |

### 6.7 交付批次（分三次验收）

| 批次 | 覆盖 | 验收物 |
|------|------|--------|
| **批次 1** | Phase 0 + Phase 1 | 缺陷修复验证记录、评测框架代码、单测结果、CLI 使用示例 |
| **批次 2** | Phase 2 + Phase 3 + Phase 4 | `manifest.json`、语料/查询统计、`RERANKER-DESIGN.md`、延迟实测、before/after 报告 |
| **批次 3** | Phase 5 + Phase 6 | `HYBRID-RETRIEVAL-DESIGN.md`、迁移与回滚记录、混合检索对照数据、终版报告 + 审查记录 |

---

## 7. 已锁定决策

| # | 决策点 | 锁定结论 |
|---|--------|----------|
| Q1 | 评测语料来源 | 公开中文基准子集（`mteb/T2Retrieval` 首选，`mteb/DuRetrieval` 交叉验证） |
| Q2 | 运行模式 | 双模式：`InMemoryRetriever` 离线确定性单测 + `QdrantRetriever` 端到端真实链路 |
| Q3 | Embedding 方案 | **维持现状**（本地 `sentence-transformers` + `BAAI/bge-base-zh-v1.5`）。切换 `bge-m3` 作为可选优化项，非本期必做——存量 602 chunk 为 768 维，切换需重索引，与 Phase 5 合并执行更经济 |
| Q4 | Reranker 集成范围 | 仅 `KnowledgeBaseService.search()`；Agent 工具与工作流节点不单独集成（其检索路径经由同一 Service，自动受益） |
| Q5 | Reranker 模型 | `BAAI/bge-reranker-v2-m3`（离线缓存） |
| Q6 | 混合检索方案 | ~~Qdrant 原生稀疏向量 + 服务端 RRF~~ → **改为「命名稠密 + 命名稀疏」双路查询 + 应用层 min-max 归一化加权融合（α 默认 0.7）」**。实测等权 RRF 使 MRR@10 −7.33pp / nDCG@10 −6.03pp，已被否决 |
| Q7 | 计划归属 | 单计划单目录（`docs/rag-eval/`） |

> **Q3 说明**：v1.1 原决策为「切换到 bge-m3」。经复核，当前存量数据为 `bge-base-zh-v1.5`（768 维），切换 embedding 模型**必然触发全量重索引**，而 Phase 5 本就需要重索引——故建议将 embedding 切换并入 Phase 5 评估，避免两次重建。**此项需确认**。

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 语料为 2 万段落子集 | 绝对 Recall 偏乐观 | 主结论限定为相对增益；采样参数写入 `manifest.json` 与报告 |
| `huggingface.co` 不可达 | 数据集下载失败 | 统一 `HF_ENDPOINT=https://hf-mirror.com` |
| 本机 `HTTP_PROXY` 导致 localhost 探测误判 502 | 环境验证结论错误 | 所有本地探测加 `--noproxy '*'` |
| reranker 首次加载耗时 | 检索冷启动变慢 | lazy singleton + 启动预热；记录冷启动耗时 |
| CPU 推理 reranker 慢（v2-m3 为 568M 参数） | 线上体验下降 | 记录 p50/p95；`candidate_k`/`batch_size`/`max_length` 可调；优先 MPS |
| 分块边界切断相关段落 | Recall 天花板被人为压低 | Phase 2 任务 2.6 专项检测 |
| Phase 5 重索引停机 | 服务中断 | 双写 + 灰度 + 回滚；低峰期执行 |
| 新增 `fastembed`/`onnxruntime` 增大镜像 | 部署体积增加 | 合并镜像层、锁定版本；必要时退回应用层 BM25 |
| 修改 `search()` 语义影响既有调用方 | 线上回归 | 新增参数全部默认 `None`；默认开关关闭时行为等价；回归门禁断言 |
| 磁盘可用空间偏紧 | 依赖安装或数据集落盘失败 | 仅装 CPU 版 torch；镜像下载后清理中间缓存 |

---

## 9. 已知不确定性（需实测）

1. 线上实际 embedding 维度与 collection 维度是否一致（存量 602 chunk 为 768 维，需确认对应模型）。
2. A2 向量删除是否真正生效（原异常被吞，Phase 0 任务 0.3 实测）。
3. MySQL 知识库三表是否已建（D4 复核）。
4. D9：软删文档的向量是否仍参与召回。
5. reranker 在本机 MPS 上的实际吞吐；v2-m3 在 CPU 上的延迟是否可接受。
6. 采样语料入库后，相关段落能否被完整切分为可召回 chunk。
7. Qdrant 1.14 是否支持已有 collection 原地扩列（Spike S1）。

---

## 10. 环境验证记录（2026-09-11 实测）

| 项 | 方式 | 结果 |
|----|------|------|
| Qdrant 6333 | `curl 127.0.0.1:6333/collections` | **已运行**；含 1 个 collection `kb_e5dd6706-…` = **602 points / 768 维** |
| MySQL 3306 / Redis 6379 / API 8000 / 前端 80 | 端口探测 | 全部 **OPEN** |
| Docker 容器 | `docker ps` | `ai-studio-{mysql,redis,qdrant,backend,celery-worker,frontend}` 全部 **healthy** |
| Python venv | 路径探测 | **位于项目根** `/Volumes/Document/qiugu/AI-Studio/.venv`（Python 3.12.13），非 `backend/.venv` |
| reranker 权重 | HF hub | `models--BAAI--bge-reranker-v2-m3`（2.1 GB）✅ |
| embedding 权重 | HF hub | `models--BAAI--bge-m3`（4.3 GB）✅ |
| 磁盘 | `df -h /` | 274 GiB 容量，**可用约 9.6 GiB**（偏紧） |
| 代理 | `env` | `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:52416` |
| A1 修复校验 | AST 全量扫描调用点 | 3 处调用点参数名全部一致 ✅ |
| `PointIdsList` 可用性 | 容器内 import | 可用 ✅ |

> v1.1 附录记录的 D1/D2/D3 阻塞项经复核已不适用（provider 已切本地、Qdrant 已运行）。

---

## 11. 执行确认

本计划为 v2.0 合并版，**待评审**。请确认：

1. §7 Q3 的调整——**embedding 切换（bge-m3）并入 Phase 5 统一重索引**，本期不单独执行，是否同意？
2. §6.7 的三批次交付节奏是否符合预期？
3. 是否同意将 `docs/plan-knowledge-retrieval-p0-p2.md` 标记为历史文档（内容已并入本文件）？

确认后按 **批次 1 → 批次 2 → 批次 3** 顺序执行，每批次完成后运行单元测试、执行代码审查三问，并在 `docs/rag-eval/` 下更新对应文档后发起验收。

---

## 12. 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-09-11 | v1.0 → v1.1 | 初版编制；锁定 Q1–Q4 决策 |
| 2026-09-11 | **v2.0** | 与 `plan-knowledge-retrieval-p0-p2.md` 合并；A 系列缺陷修复标记为已完成；新增 Phase 5 混合检索；Reranker 模型锁定 `bge-reranker-v2-m3`；环境验证记录更新为最新实测 |
| 2026-09-12 | **v2.1** | 批次 1 交付完成：Phase 0 剩余验证全部闭环（0.2–0.4、0.6），Phase 1 评测框架落地并通过 137 项测试；D9 生产数据完成校准（301 → 0）；D4 解除；D8 等价性实测通过。交付物与证据见 [batch1-delivery.md](./batch1-delivery.md) |
| 2026-09-15 | **v2.2** | Phase 5 主体实施：**Q6 决策改写**（服务端 RRF → 应用层加权融合，实测依据见报告 §2.1）；D11 关闭；**分块参数由 1024/128 重新标定为 448/64**（原值触发 512 token 静默截断，实测 49.7% 块被截断 / 28.3% 词元未编码）；Phase 5 完成状态表补入。交付物见 [FIX-AND-HYBRID-RETRIEVAL-REPORT.md](./FIX-AND-HYBRID-RETRIEVAL-REPORT.md) |
| 2026-09-15 | **v2.3** | 5.4 / 5.6 / 5.8 由独立排期**合并为一次重建**，产出 [PHASE5-REBUILD-PLAN.md](./PHASE5-REBUILD-PLAN.md)：元数据落位（段内切分 + 页码/标题）、一次迁移两列（`heading_path` + `active_collection` 灰度指针）、双写/灰度/回滚，并实测重建规模（评测 28,771 → 52,068 块 ≈10.3 h；生产 301 → 634 块 ≈7.5 min）。前置校验闭环：上传原件 1/1 在位 |
