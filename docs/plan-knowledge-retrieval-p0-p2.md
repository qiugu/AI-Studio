# 知识库检索增强实施计划（P0 – P2）

> ⚠️ **本文件已废弃（历史文档）**：内容已合并至 [`docs/rag-eval/PLAN.md`](rag-eval/PLAN.md) **v2.0**。
> 合并原因：项目中已存在同日编制、范围重叠的 `docs/rag-eval/PLAN.md`（v1.1，已通过 Q1–Q4 决策）。经评审决定合并为单一计划，统一置于 `docs/rag-eval/`。
> 本文件保留仅作历史追溯，**后续一切以 `docs/rag-eval/PLAN.md` 为准**。

> **文档性质**：实施计划（**待评审**）。经确认后方进入编码阶段。
> **上游依据**：`docs/knowledge-base-enhancement-assessment.md`（增强评估报告，2026-09-11）
> **范围授权**：用户已明确「做到 P0、P1、P2 即可，不做 GraphRAG」
> **编制日期**：2026-09-11

---

## 0. 范围与目标

### 0.1 范围边界

| 纳入 | 排除（本期不做） |
|------|------------------|
| P0：检索链路缺陷修复 + 评测基线建设 | 图数据库（Neo4j / Kuzu 等） |
| P1：Reranker 精排 | GraphRAG / 实体关系抽取 / 社区摘要 |
| P2：混合检索（稠密 + 稀疏）+ 分块质量修复 | 知识图谱可视化 |
| 配套：单元测试、文档同步 | PDF OCR / 版面结构还原（留待后续单独立项） |

> **设计约束**：所有改造必须保留「后续可平滑接入图能力」的扩展点，但不预留空实现代码。具体做法是——检索层抽象为「多路召回 → 融合 → 精排」的管线，未来新增图召回路径时只需追加一个 recall provider，不改动既有代码路径。

### 0.2 目标（可度量）

| 目标 | 度量方式 | 目标值 |
|------|----------|--------|
| G1 检索链路可用 | Agent 工具 / Workflow 节点端到端调用不再抛异常 | 100% 通过 |
| G2 建立评测基线 | 评测集规模 | ≥ 30 条 query + ground truth 标注 |
| G3 Reranker 生效 | Recall@5 / NDCG@10 相对 P0 基线 | Recall@5 提升 ≥ 15 个百分点（若基线已很高则改为 NDCG@10 提升 ≥ 10%） |
| G4 混合检索生效 | 含编号/型号/专名的 query 命中率 | 该类 query 的 Recall@10 提升 ≥ 20% |
| G5 回归保障 | 知识库相关单测 | ≥ 15 个用例，全部通过 |

> **G3 说明**：评测集在 P0 阶段建成后，先测出真实基线，再据此校准目标值。若基线已高于 85%，绝对值提升空间有限，届时以 NDCG@10 的相对提升为准。目标值在 P0 结束时最终确认。

---

## 1. 阶段总览

| 阶段 | 内容 | 新增依赖 | 是否需重索引 | 工作量 |
|------|------|----------|--------------|--------|
| **P0** | 8 项缺陷修复 + 评测集建设 + 单测补齐 | 无 | 否 | 3–5 人日 |
| **P1** | Reranker（本地 CrossEncoder + API 降级） | 无（复用 `sentence-transformers`） | 否 | 3–5 人日 |
| **P2** | 混合检索 + 分块质量修复 + 元数据增强 | 待定（见 §4.1） | **是** | 5–8 人日 |
| | | | **合计** | **11–18 人日** |

**执行顺序**：P0 → P1 → P2，串行。理由：P1 的价值需 P0 的评测基线来度量；P2 触发全量重索引，应放在检索逻辑稳定之后，避免重复重建。

---

## 2. P0：链路修复与评测基线

### 2.1 缺陷修复清单

| ID | 文件:行 | 现状问题 | 修复方案 | 风险 |
|----|---------|----------|----------|------|
| **A1** | `services/agent.py:233`<br>`services/workflow_engine.py:360` | 调用 `search(query_text=...)`，服务层签名为 `query` → `TypeError`，**功能失效** | 统一参数名为 `query`（与 REST 层 `api/knowledge.py:349` 一致）；同步修正 `knowledge.py:230` 的 `kb_id: int` 注解为 `str` | 低 |
| **A2** | `services/knowledge.py:206-209` | `qdrant.delete(points_selector=chunk.vector_id)` 传字符串，Qdrant 期望 ID 列表 → 删除静默失败（异常被 `except Exception: pass` 吞掉） | 改用 `PointIdsList(points=[...])` 或 `points_selector=[id]`；**并改为记录 warning 日志**，不再静默丢弃 | 低 |
| **A3** | `services/knowledge.py:196` | `delete_document` 裸写 `self.db.query(KnowledgeChunk)`，违反 `CLAUDE.md` 多租户必须走 `BaseRepository` 的约定 | 在 `KnowledgeChunkRepository` 新增 `list_by_doc_ids()`；Service 改走仓储 | 低 |
| **A4** | `services/knowledge.py:272-282` | 逐条 `get_by_vector_id()` 回表 + `chunk.document` 懒加载 → N+1 查询（top_k=5 时最多 11 次查询） | 新增 `KnowledgeChunkRepository.list_by_vector_ids(ids)`，一次 `WHERE vector_id IN (...)` + `joinedload(KnowledgeChunk.document)` | 低 |
| **A5** | `services/knowledge.py:235,264`<br>`config.py` | `score_threshold=0.5` 硬编码魔数，散落于服务与 API 默认值 | 提升为 `config.retrieval_score_threshold`（默认 0.0，交由 Reranker 阶段裁量），API 与 Service 均引用配置 | 低 |
| **A9** | `backend/tests/` | 无任何知识库相关测试 | 见 §2.3 测试清单 | 低 |
| **A10** | `services/knowledge.py` 等多处 | 类型注解与实现不符（`kb_id: int` 实为 str UUID） | 全量校正知识库模块的类型注解 | 低 |
| **A8** | `AGENTS.md:82,101` | 架构图写 `PG + pgvector`、目录注释写 `pgvector 连接`，实际为 Qdrant | 更新为 Qdrant，消除文档与实现偏差 | 低 |

> **A5 补充说明**：当前 `score_threshold=0.5` 对已归一化的 bge 向量属偏紧设定，会显著压缩召回。P0 阶段先降为可配置项并将默认值调低（建议 0.0，由 `top_k` 控制），**具体取值在评测集测出召回曲线后于 P1 定稿**。

### 2.2 评测集与指标（G2）

**这是 P1/P2 的前置条件——没有基线就无法证明增强有效。**

| 项目 | 设计 |
|------|------|
| 数据来源 | 优先使用现有知识库真实文档；若环境无数据，构造覆盖「制度条款 / 产品手册 / 技术文档 / 表格类」的样例文档集 |
| 规模 | 30–50 条 query，每条标注 1–3 个 ground-truth chunk（`vector_id` 或 `chunk_id`） |
| 问题类型分层 | ① 事实查询（定义/参数）② 术语/编号精确匹配 ③ 语义改写 ④ 多文档关联 |
| 存储 | `backend/tests/eval/dataset.json`（query + ground truth + 类型标签） |
| 指标 | Recall@5、Recall@20、MRR@10、NDCG@10；按问题类型分组统计 |
| 执行 | `backend/tests/eval/run_eval.py`，输出 Markdown 报告，结果落盘为基线快照 |
| 可比性 | 评测集版本化（`dataset.json` 含 `version` 字段），基线快照存档，各阶段对比使用同一版本 |

> **注意**：类型 ③（语义改写）用于评估稠密检索；类型 ②（编号/专名）用于评估稀疏检索的必要性——这两类之间的表现差距，是 P2 立项的量化依据。

### 2.3 测试清单（G5）

| 测试文件 | 覆盖内容 |
|----------|----------|
| `test_knowledge_service_signature.py` | 用 `inspect.signature` 断言 `search()` 参数名，并以 AST 校验**所有调用点**关键字一致——防止 A1 类问题回归 |
| `test_knowledge_search.py` | 检索链路：空集合、阈值过滤、`top_k` 截断、结果字段完整性（mock Qdrant） |
| `test_knowledge_delete.py` | 文档删除时向量删除被正确调用（断言 `PointIdsList` 入参） |
| `test_repository_tenant_isolation.py` | 所有知识库仓储方法均带 `tenant_id` 过滤 |
| `test_text_splitter.py` | 分块边界、空文本、超长段落、分隔符优先级 |

### 2.4 验收标准

- [ ] Agent 知识库工具与 Workflow 知识库节点端到端调用成功返回结果（不再抛异常）
- [ ] 文档删除后 Qdrant 中对应向量确实消失（用 Qdrant count 验证）
- [ ] 检索回表查询次数从 O(top_k) 降为 O(1)（用 SQL 计数断言）
- [ ] 评测脚本可运行并输出基线报告
- [ ] 新增单测全部通过，且 `pytest` 全量套件无回归
- [ ] `AGENTS.md` 向量库描述与实现一致

---

## 3. P1：Reranker 精排

### 3.1 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 默认实现 | 本地 CrossEncoder `BAAI/bge-reranker-base` | 复用已有 `sentence-transformers`，**零新增依赖、零新增服务**；数据不出网 |
| 可插拔性 | 抽象 `RerankerClient`，provider 支持 `local` / `api` | 与现有 `EmbeddingClient` 的 provider 工厂模式保持一致，降低认知负担 |
| 降级策略 | 本地模型加载/推理失败 → 自动回退为「不重排」（返回原始向量排序），并记录 warning | 检索链路不可因 Reranker 故障而中断 |
| 两段式参数 | `recall_k`（粗召回，默认 30）→ rerank → `top_k`（返回，默认 5） | 精排需要足够候选才有意义 |
| 部署位置 | 常驻 **API 进程**侧，不进 Celery worker | 避免与 Embedding 模型在 worker 内叠加内存（评估报告 §3.4） |

### 3.2 组件设计

**新增 `backend/app/utils/rerank.py`**

```
RerankerClient(provider, model)
├─ rerank(query: str, documents: list[str], top_n: int) -> list[(index, score)]
├─ provider="local"  → sentence_transformers.CrossEncoder（进程级缓存）
├─ provider="api"    → 兼容 Cohere / SiliconFlow / Jina 的 rerank 接口
└─ 异常 → 记录 warning，返回按原序的结果（降级）

get_reranker_client(provider=None, model=None) -> RerankerClient   # 工厂函数
```

**配置项（`core/config.py`）**

```
rerank_enabled: bool = True
rerank_provider: str = "local"
rerank_model: str = "BAAI/bge-reranker-base"
rerank_recall_k: int = 30      # 粗召回候选数
rerank_top_k: int = 5          # 精排后返回数
retrieval_score_threshold: float = 0.0
```

### 3.3 改造点

| 文件 | 改造 |
|------|------|
| `utils/rerank.py` | **新建**：`RerankerClient` + 工厂函数（对齐 `embedding.py` 风格） |
| `core/config.py` | 新增上述配置项 |
| `services/knowledge.py` | `search()` 改为两段式：`recall_k` 粗召回 → Reranker → 截断 `top_k`；结果新增 `rerank_score` 字段；`rerank_enabled=False` 时退化为原逻辑 |
| `schemas/knowledge.py` | 检索结果 Schema 增加 `rerank_score` |
| `services/agent.py`<br>`services/workflow_engine.py` | 透传配置（如需按工具粒度控制） |
| `frontend/src/pages/Knowledge/KnowledgeDetail.tsx` | 检索结果展示增加 rerank 分（可选，不阻塞后端交付） |

### 3.4 可观测性

- 日志记录：召回耗时 / 重排耗时 / 候选数 / 降级事件
- 检索结果中返回 `rerank_score` 与原始 `score`，便于前端调试与人工核对

### 3.5 验收标准

- [ ] 评测集上 Recall@5 相对 P0 基线提升 ≥ 15 个百分点（或 NDCG@10 相对提升 ≥ 10%，目标以 P0 实测基线最终校准）
- [ ] Reranker 异常时链路自动降级，检索仍返回结果
- [ ] 单次检索延迟增量 ≤ 500 ms（CPU，30 候选）
- [ ] `rerank_enabled=False` 时行为与 P0 完全一致（回归测试保证）
- [ ] 新增单测覆盖：正常重排、异常降级、空候选、候选数 < top_k

---

## 4. P2：混合检索与分块质量修复

### 4.1 技术选型（**需先 spike 验证，再定稿**）

现状前提（已核实）：项目**未引入** `jieba`、`fastembed`、`onnxruntime`。

| 方案 | 实现方式 | 新增依赖 | 优势 | 风险 |
|------|----------|----------|------|------|
| **P2-A：Qdrant 原生稀疏向量** | Collection 增加 sparse named vector，索引时生成稀疏向量，Query API 用 `prefetch` + `fusion=RRF` | `fastembed`（含 `onnxruntime`，镜像 +100~200 MB）或自实现编码 | 服务端融合，单次往返，性能最优；与现有 Qdrant 架构契合 | 需确认 Qdrant 1.14 能否**原地扩列**（否则全量重建）；中文分词需额外处理 |
| **P2-B：应用层混合** | 稠密检索（Qdrant）+ 关键词检索（自实现 BM25，语料统计存 MySQL）→ 应用层 RRF 融合 | 仅 `jieba`（轻量，约 10 MB） | 依赖最轻；融合逻辑可控、可调试 | 两次查询、融合在应用侧；BM25 需自维护 IDF 统计与增量更新 |
| **P2-C：仅 Reranker 强化** | 不做稀疏检索，仅靠 Reranker 精排 | 无 | 零成本 | **不解决**编号/专名的召回缺失（粗召回漏掉的，精排无法找回） |

**推荐路径：P2-A**，但设 **Spike 前置**：

| Spike | 验证问题 | 通过标准 | 耗时 |
|-------|----------|----------|------|
| S1 | Qdrant 1.14 能否在已有 collection 上**原地添加 sparse vector 配置** | 能，则避免全量重建的停机 | 0.5 人日 |
| S2 | 中文 BM25 分词效果：`jieba` 预分词 + `fastembed Bm25` vs 自实现 BM25 | 在评测集类型 ②（编号/专名）上 Recall@10 有可测提升 | 0.5–1 人日 |
| S3 | 若 S1 不通过，评估全量重建的停机窗口与迁移脚本 | 有可行迁移路径 | 0.5 人日 |

> **决策点（评审时请确认）**：若你倾向「依赖最小化」，则选 P2-B；若倾向「性能与架构一致性」，则选 P2-A。我默认按 P2-A 编写后续步骤，Spike 结果若不利则回退 P2-B。

### 4.2 数据迁移策略

P2 涉及 Collection Schema 变更，需**全量重索引**（与分块修复合并执行，避免二次重建）：

1. 新建 collection 版本后缀（如 `kb_{id}_v2`），双写过渡
2. 用现有 `file_url` 从磁盘重新解析 → 分块 → 稠密 + 稀疏编码 → 写入 v2
3. 校验：v2 的 chunk 数与 MySQL `knowledge_chunks` 一致
4. 切换读取指向 v2，保留 v1 一个灰度周期后删除
5. 提供回滚脚本（切回 v1）

> **前置条件**：文档原文件必须仍在 `UPLOAD_DIR` 中（`doc.file_url` 指向）。实施前需先校验文件在位率，缺失的文件需提示用户重新上传。

### 4.3 分块质量修复（随重索引一并生效）

| ID | 问题 | 修复 |
|----|------|------|
| **A7** | `utils/document.py:157-174` 的 `_merge_splits` 未计入 `chunk_overlap`，声明的 128 字符重叠**实际未生效** | 实现真实重叠逻辑（回溯 `chunk_overlap` 字符），并补单元测试断言相邻 chunk 的重叠长度 |
| **元数据增强** | chunk 仅存 `chunk_index` / `source_page`（后者恒为 `None`） | 新增 `heading_path`（标题层级路径）、`source_page`（PDF 真实页码）；写入 Qdrant payload 供过滤与展示 |

> **A6（PDF OCR / 版面还原）本期不做**。理由是方案选型（`pymupdf` 布局模式 / Unstructured）会引入较大依赖与处理链路变化，且与「检索质量」主目标不直接相关，建议单独立项评估。

### 4.4 改造点

| 文件 | 改造 |
|------|------|
| `core/vector_db.py` | `get_or_create_collection()` 支持 sparse vector 配置；维度校验逻辑扩展 |
| `utils/sparse.py` | **新建**：稀疏编码器（provider 抽象，对齐 embedding/rerank 风格） |
| `utils/document.py` | 修复 `_merge_splits` 重叠；`DocumentParser` 抽取标题路径与页码 |
| `models/knowledge_chunk.py` | 新增 `heading_path` 字段（+ Alembic 迁移） |
| `services/knowledge_processor.py` | 索引管线增加稀疏编码与元数据写入 |
| `services/knowledge.py` | `search()` 增加混合召回 + RRF 融合（与 P1 的 Reranker 串联） |
| `alembic/versions/*` | 新增迁移：`knowledge_chunks.heading_path` |
| `requirements.txt` | 按 §4.1 定稿结果追加依赖 |
| `docker-compose.yml` | 若引入 `fastembed`，`hf-cache` 卷需覆盖其模型缓存路径 |

### 4.5 验收标准

- [ ] 评测集类型 ②（编号/专名）的 Recall@10 提升 ≥ 20%
- [ ] 整体 NDCG@10 不低于 P1 水平（即混合检索未引入副作用）
- [ ] 相邻 chunk 重叠长度符合 `chunk_overlap` 配置（单测断言）
- [ ] 迁移后 v2 与 MySQL chunk 记录数一致；回滚脚本可用
- [ ] 检索结果返回 `heading_path`，前端可展示来源定位

---

## 5. 测试计划

| 层级 | 内容 | 执行时机 |
|------|------|----------|
| 单元测试 | §2.3 五类 + P1 四类 + P2 三类（分块重叠、稀疏编码、融合排序） | 每阶段交付时 |
| 契约测试 | `search()` 签名一致性（AST 全量扫描调用点） | 每次提交（防止 A1 类回归） |
| 评测回归 | 评测集全量跑分，对比上一阶段基线快照 | P0 建基线后，P1/P2 各跑一次 |
| 端到端 | Agent 工具 / Workflow 知识库节点 / REST 检索三条路径各跑通 | P0 与最终交付 |
| 环境 | 需创建 `backend/.venv` 并安装 `requirements.txt`（当前尚未创建，P0 第一步） | P0 起始 |

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 评测集数据不足（无真实知识库） | 无法量化收益 | P0 第一步即构造样例文档集；G3/G4 目标值待基线实测后校准 |
| 无可用运行环境（`.venv` 未建） | 无法验证 | P0 第一步完成环境搭建；若依赖安装受阻及时反馈 |
| P2 全量重索引停机 | 服务中断 | 双写 + 灰度切换 + 回滚脚本；重建放低峰期 |
| 原文件丢失（`file_url` 失效） | 无法重建索引 | 实施前校验在位率，缺失项列出请用户补传 |
| `fastembed`/`onnxruntime` 增大镜像 | 部署体积增加 | 选 P2-B 可规避；或合并镜像层并锁定版本 |
| Reranker CPU 延迟 | 检索变慢 | 候选数可配（默认 30）；必要时切 API provider |
| 分块策略变更导致历史结果变化 | 用户感知差异 | 版本化 collection + 灰度；评测集验证不降级 |

---

## 7. 交付物清单

| 类别 | 交付物 |
|------|--------|
| 代码 | `utils/rerank.py`、`utils/sparse.py`（P2）、改造后的 `services/knowledge.py`、`knowledge_processor.py`、`vector_db.py`、`document.py`、`config.py`、`agent.py`、`workflow_engine.py` |
| 数据 | `backend/tests/eval/dataset.json`（评测集）、基线快照 |
| 测试 | `backend/tests/` 下新增 12+ 测试文件/用例 |
| 迁移 | 新增 Alembic 迁移脚本 + 索引重建/回滚脚本（`backend/scripts/`） |
| **文档**（统一置于 `docs/`） | ① `docs/plan-knowledge-retrieval-p0-p2.md`（本文档）② `docs/knowledge-retrieval-p0-p2-summary.md`（实施总结，含实测前后指标对比）③ 更新 `AGENTS.md`、`docs/core-mechanisms.md` |
| 评审材料 | 评测集跑分报告（P0 基线 vs P1 vs P2） |

---

## 8. 工作量与排期建议

| 阶段 | 任务 | 人日 |
|------|------|------|
| P0 | 环境搭建（`.venv` + 依赖） | 0.5 |
| P0 | A1–A5、A8–A10 缺陷修复 | 1.5–2 |
| P0 | 评测集构建 + 评测脚本 + 基线跑分 | 1–2 |
| P0 | 单测补齐 | 1 |
| **P0 小计** | | **4–5.5** |
| P1 | `rerank.py` + 配置 + `search()` 两段式改造 | 2 |
| P1 | 降级与可观测 + 测试 + 评测对比 | 1.5–3 |
| **P1 小计** | | **3.5–5** |
| P2 | Spike S1–S3 | 1–2 |
| P2 | 稀疏编码 + Collection Schema + 索引管线改造 | 1.5–2 |
| P2 | 分块修复 + 元数据增强 + Alembic 迁移 | 1.5–2 |
| P2 | 混合检索融合 + 迁移/回滚脚本 + 测试 + 评测对比 | 2 |
| **P2 小计** | | **6–8** |
| **合计** | | **13.5–18.5 人日** |

---

## 9. 评审决策记录（2026-09-11 已确认）

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | 范围 | ✅ 确认：P0 + P1 + P2，**排除图数据库与 GraphRAG** |
| 2 | P2 技术路线 | ✅ **P2-A：Qdrant 原生稀疏向量**（服务端 RRF 融合，接受 `fastembed` 依赖）。Spike S1–S3 仍执行，仅用于确认实施细节（原地扩列可行性、中文分词方案），不再作为路线选择依据 |
| 3 | 评测数据来源 | ✅ **使用现有真实知识库数据**（需先探查可用的知识库与文档量） |
| 4 | 重索引授权 | ✅ **授权 P2 全量重建 Qdrant Collection**（实施前先校验 `UPLOAD_DIR` 原文件在位率） |
| 5 | 交付节奏 | ✅ **分三次交付验收**：P0 完成后即验收，再启动 P1；P1 验收后启动 P2 |

**执行约定**：每阶段完成后执行 ① 单元测试 ② 代码审查（可读性 / 性能与安全 / 规范遵循）③ 在 `docs/` 下更新实施总结文档，并向用户发起该阶段验收。

**编制说明**：本文档为计划，**尚未编写任何生产代码**。当前状态：**P0 执行中**。

---

## 10. 变更日志

| 日期 | 变更 |
|------|------|
| 2026-09-11 | 初版编制；同日完成评审，§9 记录 5 项决策；开始 P0 执行 |
