# RAG 缺陷修复 + 混合检索 —— 实施计划（v1.0，待评审）

- 编制日期：2026-09-14
- 依据文档：[E2E-VERIFICATION-REPORT.md](./rag-eval/E2E-VERIFICATION-REPORT.md)（P1/P2/P3 缺陷清单）、[plan-knowledge-retrieval-p0-p2.md](./plan-knowledge-retrieval-p0-p2.md)（既有已批准计划）
- 执行环境：Docker Compose 运行栈（镜像构建于 2026-09-14 12:37，容器代码与工作区 sha256 逐字节一致）
- 状态：**计划，尚未改动任何生产代码**

---

## 0. 结论摘要

1. **P1 → P2 → P3 三级缺陷的修复方案已确定**，共 9 项，全部为小范围、可单测覆盖的改动，不影响主链路契约。
2. **混合检索可以做，但必须放弃既有计划中「服务端等权 RRF」的路线**——本轮实测证明等权 RRF 会**显著损害**排序指标。
3. **实测可实现的增益远小于既有计划的验收目标**：最优配置下 MRR@10 +1.20pp、nDCG@10 +1.63pp（既有计划要求「编号/专名类 Recall@10 提升 ≥20%」）。因此混合检索**是否值得其迁移成本，需要你重新裁决**（§5.3 给出三个方案）。

---

## 1. 范围与执行顺序

| 序 | 批次 | 内容 | 是否需评审 |
|---|---|---|---|
| 1 | **P1 修复** | P1-A 读取侧文档级删除过滤；P1-B Agent 知识库工具闭包绑定 | 方案已定 |
| 2 | **P2 修复** | P2-C 知识库删除级联；P2-D 文档可清理性；P2-E 检索异常可观测性；P2-F 工具异常兜底 | 含 2 个待裁决项 |
| 3 | **P3 修复** | P3-G 分块重叠；P3-H 去重（验证性）；P3-I 存量数据对齐 | 含 1 个待裁决项 |
| 4 | **混合检索** | 依 §5 实测结论，按你的裁决执行或不执行 | **必须裁决** |

每批次完成后执行：单元测试 → 代码审查（可读性 / 性能与安全 / 规范遵循）→ 更新文档 → 向你发起验收。**批次间不并行**，避免回归定位困难。

---

## 2. P1 修复设计（正确性/安全）

### 2.1 P1-A｜已软删除文档的分块仍会被检索命中

| 项 | 内容 |
|---|---|
| 根因 | `search()` 回表只过滤**分块级** `deleted_at`，不判定所属文档是否已软删。写入侧 D9 级联只对「此后发生的删除」有效，读取侧对历史数据与异常路径**零防御** |
| 位置 | `app/repositories/knowledge.py:108-127`（`KnowledgeChunkRepository.list_by_vector_ids`） |
| 实测 | 检索 `kb_e5dd6706…` 返回 `doc=4626a81d…`（`deleted_at=2026-09-11`）的分块 |
| 修法 | 在 `list_by_vector_ids` 上 `join KnowledgeDocument` 并追加 `KnowledgeDocument.deleted_at IS NULL`（同时约束同租户），使**所有消费方**（REST / Agent 工具 / 工作流节点 / 评测）一并获得保护，而非只在 `search()` 里打补丁 |
| 不改什么 | 不修改 `search()` 的返回结构；不改动精排与去重顺序 |
| 测试 | 新增 `tests/test_knowledge_search_scope.py`：① 文档已软删的分块被排除；② 文档存活的分块正常返回；③ 跨租户文档的分块不被返回 |
| 验收 | 对 `kb_e5dd6706…` 检索 `"注意力机制"`，结果中不再出现 `doc=4626a81d…` |

### 2.2 P1-B｜Agent 知识库工具闭包晚绑定导致串库

| 项 | 内容 |
|---|---|
| 根因 | `kb_id` / `top_k` 是 `_build_langchain_tools` 的**函数级局部变量**，闭包共享同一 cell，循环结束后取最后一个值 |
| 位置 | `app/services/agent.py:341-359` |
| 实测 | 同时绑定「不存在的库」与「真实库」，两个工具均返回真实库内容（2562 字符） |
| 修法 | 改为默认参数绑定：`def knowledge_search_func(query: str, _kb_id=kb_id, _top_k=top_k)`，与同文件 `api`（`app/services/agent.py:372-378`）/ `function` / `workflow` 分支写法一致 |
| 测试 | 新增 `tests/test_agent_knowledge_tool.py`：绑定 2 个不同知识库，断言两工具实际检索的 `kb_id` 不同（用替身捕获调用参数） |
| 验收 | 绑定库 A + 库 B 时，库 A 工具只查库 A |

---

## 3. P2 修复设计（可靠性/可维护性）

### 3.1 P2-C｜删除知识库不级联清理文档、分块与向量

| 项 | 内容 |
|---|---|
| 位置 | `app/services/knowledge.py:123-127`（`delete_knowledge_base`） |
| 实测 | `DELETE /knowledge-bases/{id}` 返回 200 后：文档仍可查（200/completed）、分块仍在（total=1）、Qdrant 集合仍存在（points=1） |
| 修法 | 抽取 `_purge_document(doc, deleted_at)` 私有方法（**先取分块 → 删向量 → 再软删分块**，顺序不可调换，理由已在 `delete_document` docstring 中记录）；`delete_knowledge_base` 遍历该库全部存活文档逐份调用；随后删除 Qdrant 集合；最后软删 KB 并归零计数 |
| 新增仓储方法 | `KnowledgeDocumentRepository.list_all_by_kb(kb_id)`（不受分页限制） |
| 待裁决 | **回收粒度**：① 删除整个 Qdrant 集合（彻底回收存储，不可恢复）；② 仅按 `doc_id` 清空向量、保留空集合（保留未来「恢复知识库」的可能性） |
| 测试 | `tests/test_knowledge_delete_cascade.py`：建 2 份文档各含分块 → 删库 → 断言文档/分块软删、向量删除调用发生、KB 软删、计数归零 |
| 验收 | 删库后 `GET /documents/{id}` 返回 404；Qdrant 无残留（按裁决语义） |

### 3.2 P2-D｜知识库删除后，其文档进入「不可清理」状态

| 项 | 内容 |
|---|---|
| 根因 | `delete_document` 首行 `self.get_knowledge_base(doc.kb_id)`，而该方法过滤已软删知识库 → 库删后其文档永久无法清理（P2-C 的放大器） |
| 位置 | `app/services/knowledge.py:228-239` |
| 修法 | 改为先取文档，再用**不过滤软删**的方式定位 KB（新增 `KnowledgeBaseRepository.get_by_id_including_deleted`）；KB 不可见时跳过计数维护，但**仍执行文档/分块/向量的完整回收** |
| 测试 | `tests/test_knowledge_delete_cascade.py` 内补用例：KB 已软删 → 删文档成功且向量被清理 |
| 验收 | 复现既有失败路径不再返回 404 |

### 3.3 P2-E｜`search()` 吞掉 Qdrant 异常，故障与空结果不可区分

| 项 | 内容 |
|---|---|
| 位置 | `app/services/knowledge.py:353-366` |
| 实测影响 | 首轮勘察曾因此把「集合不存在」误读为「库里没有向量」，得出与事实相反的结论 |
| 修法（推荐，**非破坏性**） | 引入 `SearchOutcome`（`results` / `degraded` / `reason` / `method` / `candidate_count`）；新增 `search_with_diagnostics()` 承载诊断信息，`search()` 保持**当前 list 返回契约不变**（委托前者）；异常按因分类记录：集合缺失记 `error`（配置/数据故障），Qdrant 不可达记 `warning`（瞬时故障）；API 层在降级时回写响应头 `X-Retrieval-Degraded` / `X-Retrieval-Reason` |
| 为何不改成结构化 body | 前端 `searchKnowledgeBase` 直接消费 `SearchResult[]`（`frontend/src/api/knowledge.ts:132-141`），改 body 结构属破坏性变更，收益不足以抵偿联调成本 |
| 备选 | 集合缺失时直接抛 `NotFoundException`（语义更准确，但会改变「库存在而集合缺失 → 200 + []」的既有行为） |
| 测试 | `tests/test_knowledge_search_diagnostics.py`：Qdrant 抛异常 → `degraded=True` 且 `reason` 正确；正常路径 → `degraded=False` 且 `results` 与旧契约逐条一致 |
| 验收 | 人为删除集合后检索：日志可区分、响应头置位、业务流程不中断 |

### 3.4 P2-F｜knowledge 工具无异常兜底，错误直接穿透到 Agent

| 项 | 内容 |
|---|---|
| 位置 | `app/services/agent.py:346-351` |
| 实测 | 绑定不存在的库 → `NotFoundException` 直接抛出（LangChain `Tool` 默认不吞异常，会中断 ReAct） |
| 修法 | 工具内 `try/except`，转为可读失败文本返回给模型（与同文件 `api` 分支 `app/services/agent.py:414-415` 的取向一致）；降级时（P2-E）显式说明「检索未生效」而非「未找到相关知识」，避免模型把故障当事实 |
| 安全 | 不回传原始栈信息，仅回传异常类别 + 简短原因 |
| 测试 | `tests/test_agent_knowledge_tool.py` 内补用例：库不存在 → 返回字符串而非抛异常；降级 → 文案含「检索未生效」 |
| 验收 | 绑定非法知识库时 Agent 不中断 |

---

## 4. P3 修复设计（质量与一致性）

### 4.1 P3-G｜`chunk_overlap` 未生效（D11）

| 项 | 内容 |
|---|---|
| 位置 | `app/utils/document.py:157-174`（`_merge_splits`） |
| 根因 | 长度比较为 `len(current) + len(s) + separator_len`，**从未把 `chunk_overlap` 纳入计算**，声明的 128 字符重叠实际为 0 |
| 修法 | 改为标准回溯算法（对齐 LangChain `RecursiveCharacterTextSplitter._merge_splits`）：追加新片段前，从 `current` 头部弹出片段，直到剩余长度 ≤ `chunk_overlap`，使新块以前一块的尾部片段开头；块长上限仍受 `chunk_size` 约束，且每一块仍是原文的**连续子串**（片段由 `text.split(separator)` 得到，用分隔符重新拼接可还原原文） |
| 连带影响 | 分块边界变化 → 新入库文档块数约 +12%（`chunk_overlap=128 / chunk_size=1024`）；**既有 Qdrant 索引不变**，`index_manifest.json` 中 `chunk_overlap=128` 对既有索引属「名不副实」（实际 0），需在文档中显式说明；重叠收益**只能在重索引后测量** |
| 测试调整（必须） | `tests/test_text_splitter.py`：① 移除 `test_consecutive_chunks_should_overlap` 的 `strict xfail`（修复后会 XPASS 并使测试失败）并移入不变量类；② `test_overlap_helpers_agree_on_zero_overlap`（断言 `== 0`）需改为断言「重叠长度 > 0 且 ≤ chunk_overlap」；③ 保留并复核 `test_chunks_are_substrings_of_source`、`test_chunk_order_preserved` 两条不变量 |
| 验收 | 相邻块重叠 ∈ (0, chunk_overlap]；块长 ≤ chunk_size；块顺序与子串不变量成立 |

### 4.2 P3-H｜检索结果去重（**工作区已实现，本轮仅验证与文档化**）

工作区未提交改动已包含：`_dedupe_by_content`（`app/services/knowledge.py:400-442`）、配置 `retrieval_dedup_enabled` / `retrieval_fetch_multiplier`（`app/core/config.py:88-98`）、上传侧「同名同大小」重复拦截（`app/services/knowledge.py:163-179`）、测试 `tests/test_knowledge_search_dedup.py` / `tests/test_knowledge_upload_dedup.py`。**本轮不改代码**，仅：① 纳入回归测试范围；② 在交付文档中说明「写入侧拦截 + 读取侧折叠」的双层设计与已知局限（改名重传无法识别）。

### 4.3 P3-I｜存量数据不一致对齐

| 项 | 内容 |
|---|---|
| 现状 | `kb_e5dd6706…`：文档/分块/向量三方统计不符；`4626a81d…` 已软删但 301 个分块存活、向量在库（P1-A 的成因数据） |
| 修法 | 新增 `backend/scripts/align_knowledge_consistency.py`：**默认只读出一份差异报告**（doc 已删而分块存活 / 分块无向量 / `kb.chunk_count` 与存活分块不符 / `doc.chunk_count` 与实际不符）；加 `--apply` 才执行对齐（软删孤儿分块 + 删除其向量 + 重算计数），支持 `--kb-id` 限定范围与 `--dry-run` 默认值 |
| 与既有脚本关系 | 仓库已有 `backend/scripts/repair_orphan_vectors.py`，实施前先核对其覆盖范围，能复用则复用，不新建重复工具 |
| 待裁决 | 是否在本轮**执行**对齐（会影响「大模型」知识库的检索结果：`4626a81d…` 的分块将从召回中消失，属**预期内的正确变化**） |
| 验收 | 报告前后对比：三方统计一致；P1-A 的复现用例结果不再含已删文档 |

---

## 5. 混合检索：实测结论与方案裁决

### 5.1 技术前提（已实测，Qdrant 1.19.1 / qdrant-client 1.14.2）

| 实验 | 结果 |
|---|---|
| 向既有集合（未命名稠密向量）追加稀疏向量 | ❌ 报 `Not existing vector name error`，**无法原地扩列** |
| 新建集合：命名稠密 `dense` + 命名稀疏 `text` | ✅ 可用 |
| `prefetch`（稠密 + 稀疏）+ `fusion=rrf` | ✅ 可用，返回 RRF 分 |
| 纯稀疏查询 | ✅ 可用 |

**推论**：混合检索要求集合采用「命名稠密 + 命名稀疏」布局，既有集合（`kb_rageval_t2r` / `kb_e5dd6706…` / `kb_aa42da04…`）**必须重建或新建后回填**。回填可复用现有稠密向量（scroll 导出→导入），**无需重算 embedding**；稀疏向量需重新计算。

### 5.2 实测结论（基于 100 条真实查询 + 真实集合 `kb_rageval_t2r`）

实验脚手架正确性已自证：`dense(fetch=50) + 段落折叠` 与 `reports/baseline.json` **逐位一致**（Recall@5 0.8667 / MRR@10 0.8423 / nDCG@10 0.8381）。

| 配置 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | MAP@10 |
|---|---|---|---|---|---|
| 基线（dense-only） | 0.8667 | 0.8900 | 0.8423 | 0.8381 | 0.8116 |
| 词法单独（单字+二字组 BM25） | 0.7183 | 0.7433 | 0.6774 | 0.6750 | 0.6403 |
| **等权 RRF**（dense+lex，既定路线） | 0.8017 | 0.8617 | **0.7690 (−7.33pp)** | **0.7778 (−6.03pp)** | 0.7417 |
| 加权 RRF（dense:lex = 10:1，最优） | 0.8767 | 0.8950 | 0.8329 (−0.94pp) | 0.8368 (−0.14pp) | 0.8084 |
| **归一化分数融合 α=0.7（有 IDF）** | **0.8817** | **0.9050** | **0.8543 (+1.20pp)** | **0.8544 (+1.63pp)** | **0.8296** |
| 归一化分数融合 α=0.6（无 IDF） | 0.8767 | 0.9000 | 0.8516 (+0.93pp) | 0.8493 (+1.12pp) | 0.8239 |

三条关键发现：

1. **等权 RRF 有害**：MRR@10 −7.33pp、nDCG@10 −6.03pp。原因是词法分支显著弱于稠密分支（Recall@5 差 −14.8pp），等权融合让噪声词法的排名挤掉稠密的正确项。**加权 RRF 也无法使 MRR/nDCG 转正**（±1pp 内）。
2. **只有「归一化分数融合 + 稠密主导」可行**：`score = α·norm(dense) + (1−α)·norm(sparse)`，α≈0.6–0.8 时 MRR/nDCG 全为正，α=0.7 最优。α 在 0.6/0.7/0.8 三点均为正，**说明增益不是刀刃式调参的结果**。
3. **IDF 可以去掉，但增益缩水约 30%**：无 IDF（无状态编码器）时 MRR@10 +0.93pp、nDCG@10 +1.12pp；带 IDF（需维护每库语料统计）时 +1.20pp / +1.63pp。这决定了落地成本量级。

### 5.3 增益的稳健性与边界（重要，直指既有决策的前提）

| 分组 | n | MRR@10 Δ | nDCG@10 Δ | Recall@5 Δ |
|---|---|---|---|---|
| 含数字/拉丁（**代理「编号/专名」类**） | 25 | **−0.33pp** | **−0.53pp** | +4.00pp |
| 纯中文 | 75 | +1.71pp | +2.34pp | +0.67pp |
| rel1（单相关） | 80 | +1.50pp | +1.49pp | +1.25pp |
| rel2 | 17 | 0.00pp | +2.59pp | +2.94pp |

逐查询胜负（MRR@10）：改善 7 / 恶化 4 / 持平 89。

**这里必须指出两点与既有已批准计划的冲突**：

- 既有计划 §9 决策 2 定为「Qdrant 原生稀疏 + 服务端 RRF」。**实测该路线（等权 RRF）会使 MRR −7.33pp / nDCG −6.03pp**，与「提升质量」的目标相反。
- 既有计划 §4.5 的验收标准是「编号/专名类查询 Recall@10 提升 ≥20%」。但 ① 当前评测集按**相关数**（rel1/rel2/rel3plus）分组，**没有该类别标签**；② 在「含数字/拉丁」这一代理分组上，Recall@5 仅 +4.00pp，且 **MRR/nDCG 反而略降**——即混合检索在它本应解决的类别上改善的是召回、不是排序，且**远达不到 20% 的目标**。
- 补充限定：本评测集为 T2Retrieval（语义问答），可能**低估**混合检索在「企业知识库（含编号、型号、代码、专名、多语言混排）」场景下的价值；反之亦然。**这一点无法由现有数据裁决，需要你的产品判断。**

### 5.4 三个可选方案

| 方案 | 内容 | 增量成本 | 实测收益 | 主要风险 |
|---|---|---|---|---|
| **A 不做混合检索** | 保持 dense-only，把预算投向精排（需先补齐 `bge-reranker-v2-m3` 权重） | 0 | 0 | 放弃 +1pp 级增益；既有计划中的 Phase 5 作废 |
| **B 实做加权分数融合**（推荐若追求指标） | 集合改「命名稠密 + 命名稀疏」；检索发**两次** Qdrant 查询（dense / sparse），应用层做 min-max 归一化融合（α 可配，默认 0.7）；**不使用服务端 RRF**；新集合按新布局创建，旧集合提供回填脚本；功能开关默认 **off**，评测门禁通过后再开 | 集合布局改造 + 回填脚本 + 稀疏编码器 + 稀疏入库管线 + 双查询融合 + 评测门禁 | MRR@10 +0.93~1.20pp、nDCG@10 +1.12~1.63pp、Recall@5 +0.67~1.50pp | 二次往返；α 需标定（当前最优值在 100 条查询上得到，存在乐观偏差）；旧集合需回填才生效 |
| **C 触发式兜底** | 稀疏分支不参与常规排序，仅当 dense 最高分低于阈值时启用 | 同 B 的存储侧成本 | 未实测（可在实现前补一组探针） | 阈值标定与可解释性成本高 |

**推荐**：若以「指标可验证提升」为目标 → **方案 B**（并接受其为 +1pp 级的小幅提升）；若以「投入产出比」为目标 → **方案 A**，把同等算力投向精排（精排未完成是当前更大的质量缺口，见 E2E 报告 §6）。**Spike 已在本轮完成**，既有计划的 S1/S2/S3 三个 Spike 均已有答案：S1 = 不能原地扩列；S2 = 自实现 BM25（无需 jieba/fastembed）；S3 = 回填可行且无需重算稠密。

### 5.5 方案 B 的落地要点（若采纳）

| 组件 | 改造 |
|---|---|
| `app/utils/sparse.py`（新建） | 稀疏编码器：分词（ASCII 词 + 中文单字 + 二字组）、BM25 词权重（`k1=1.2`/`b=0.75`）、词元→`uint32` 索引的稳定哈希；IDF 通过可选的语料统计注入，缺省为无状态模式 |
| `app/core/vector_db.py` | `get_or_create_collection` 支持命名稠密 + 命名稀疏；新增 `search_sparse_points`；**保留 `search_points` 语义不变**（评测与线上共用入口的约束不可破坏） |
| `app/services/knowledge_processor.py` | 入库时额外生成稀疏向量并随稠密一起 upsert |
| `app/services/knowledge.py` | `search()` 增加融合分支：`dense` 与 `sparse` 各取 `fetch_k` → 归一化 → 加权融合 → 去重 → 精排 → 截断；关闭时**行为与当前严格等价** |
| `app/core/config.py` | `retrieval_hybrid_enabled`（默认 false）、`retrieval_hybrid_alpha`（默认 0.7）、`retrieval_sparse_top_k` |
| `app/rag_eval/retrievers.py` | 新增 `HybridRetriever`，与线上共用同一融合函数（口径一致性约束） |
| `backend/scripts/`（新建） | 集合回填脚本（scroll 导出稠密 → 建新布局集合 → 写入稠密 + 计算稀疏） |
| 文档 | 更新 `AGENTS.md`、`docs/core-mechanisms.md`、`docs/rag-eval/PLAN.md`（Phase 5 结论改写） |

---

## 6. 测试策略

| 层级 | 内容 |
|---|---|
| 单元测试 | 本轮新增/调整 6 个文件：`test_knowledge_search_scope.py`、`test_agent_knowledge_tool.py`、`test_knowledge_delete_cascade.py`、`test_knowledge_search_diagnostics.py`、`test_sparse_encoder.py`（若做方案 B）、`test_text_splitter.py`（调整既有 xfail） |
| 契约测试 | `search()` 签名与返回结构不变（沿用 `tests/test_knowledge_service_signature.py` 的 AST 扫描思路），确保 P2-E 不破坏前端契约 |
| 回归基线 | 容器内 RAG 相关 15 个模块的 184 用例必须保持 0 失败（当前基线：184 passed / 1 xfailed；P3-G 修复后 xfail 归零） |
| 评测回归 | 每次涉及检索路径的改动后重跑 `scripts/rag_eval.py`，与 `reports/baseline.json` 对比；**dense-only 路径必须逐位不变** |
| 端到端 | 复用本轮 E2E 脚本：① 已有库只读检索；② 建库→上传→异步处理→检索→删库，并**新增断言「删库后其文档与向量均已回收」** |

执行位置：**容器内**（依赖与模型齐备、代码已核对一致）。

---

## 7. 代码审查清单（每批次交付前执行）

- **可读性**：新增逻辑必须有「为什么」注释（如闭包绑定为何用默认参数、级联顺序为何不可调换），而非复述代码
- **性能**：回表新增的 join 不得改变既有索引命中路径；融合分支不得引入 N+1；二次 Qdrant 往返的延迟需实测并记录
- **安全**：工具异常兜底不得回传栈信息；删除级联必须限定同租户（`tenant_id` 过滤不可缺）
- **规范**：遵守 `CLAUDE.md`（自定义异常、统一响应、租户过滤用 `public_or_tenant_filter`、SSE 规范）；核心 ID 为 UUID 字符串
- **迁移**：若新增列/表，必须实际执行 `alembic upgrade` 并验证结构与 `alembic current == heads`

---

## 8. 交付物

| 类别 | 交付物 |
|---|---|
| 代码 | `app/services/knowledge.py`、`app/services/agent.py`、`app/repositories/knowledge.py`、`app/utils/document.py`、`app/core/config.py`、`app/api/knowledge.py`（方案 B 另含 `app/utils/sparse.py`、`app/core/vector_db.py`、`app/services/knowledge_processor.py`、`app/rag_eval/retrievers.py`） |
| 脚本 | `backend/scripts/align_knowledge_consistency.py`（P3-I）；（方案 B）集合回填脚本 |
| 测试 | `backend/tests/` 下 5–6 个新增/调整文件 |
| **文档（统一置于 `docs/`）** | ① 本计划 ② `docs/rag-eval/FIX-AND-HYBRID-RETRIEVAL-REPORT.md`（实施总结：逐项改动 + 前后指标 + 复现命令）③ 更新 `docs/rag-eval/PLAN.md`（Phase 5 结论）与 `docs/rag-eval/E2E-VERIFICATION-REPORT.md`（缺陷状态回写） |

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 读取侧 join 过滤改变回表性能 | 检索延迟上升 | 实测 p50/p95 与 104.59/158.24ms 基线对比；必要时为 `knowledge_documents(id, deleted_at)` 补索引 |
| 删除级联在大量文档时耗时 | 请求超时 | 分批处理并记录进度日志；超大库改为异步任务 |
| P3-G 修复改变分块边界 | 历史与新增文档分块不一致 | 现有索引不动；在文档中显式声明「既有索引实际重叠为 0」；差异只在新入库文档生效 |
| 存量数据对齐误伤 | 凭据/内容丢失 | 脚本默认 dry-run；先出报告，按裁决再执行；执行前备份相关表 |
| 方案 B 的 α 过拟合 100 条查询 | 线上增益不及预期 | 门禁用「α∈{0.6,0.7,0.8} 均不劣于基线」而非单点最优；上线默认 off，按库灰度 |
| 回填期间服务不可用 | 检索中断 | 双写过渡 + 切读后保留旧集合一个灰度周期 |

---

## 10. 待你裁决的事项

| # | 事项 | 选项 |
|---|---|---|
| 1 | **混合检索路线** | A 不做（转投精排） / **B 实做加权分数融合（推荐）** / C 触发式兜底 |
| 2 | 若做混合检索：稀疏编码器是否引入 IDF | 无状态（增益 −30%，零运维） / 带 IDF（需维护每库语料统计与增量更新） |
| 3 | P2-C 知识库删除的向量回收粒度 | 删除整个集合（彻底回收，不可恢复） / 仅清空向量保留集合 |
| 4 | P2-E 检索异常暴露方式 | 响应头 + 结构化内部结果（非破坏性） / 集合缺失时直接 404 |
| 5 | P3-I 存量脏数据 | 本轮执行对齐（会改变「大模型」库的召回） / 只出报告，暂不动数据 |

---

## 11. 变更日志

| 日期 | 变更 |
|---|---|
| 2026-09-14 | 初版编制：完成 P1/P2/P3 修复设计；完成混合检索可行性 Spike（4 组实验、5 次跑分），实测结论推翻既有计划的「服务端等权 RRF」路线，并提出三方案待裁决 |
