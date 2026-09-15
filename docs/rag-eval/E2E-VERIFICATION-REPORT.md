# RAG 全链路实测验证报告

- 文档版本：**v1.0**
- 日期：2026-09-14
- 验证对象：`backend/app/services/knowledge.py`、`backend/app/services/knowledge_processor.py`、`backend/app/utils/{document,embedding,reranker}.py`、`backend/app/core/vector_db.py`、`backend/app/services/agent.py`（knowledge 工具）
- 执行环境：Docker Compose 运行栈（`ai-studio-backend` / `ai-studio-celery-worker` / `ai-studio-mysql` / `ai-studio-redis` / `ai-studio-qdrant`，镜像构建于 2026-09-14 12:37）
- 相关文档：[PLAN.md](./PLAN.md)、[EVALUATION-REPORT.md](./EVALUATION-REPORT.md)、[RERANKER-DESIGN.md](./RERANKER-DESIGN.md)

---

## 1. 结论摘要

**主链路可以走通。** 入库（上传→解析→分块→向量化→写 Qdrant/MySQL）、在线检索（查询向量化→稠密召回→回表组装）、消费侧（REST 接口 / Agent 知识库工具）三条路径均在本轮完成真实端到端验证，全部返回预期结果。

**但存在 2 项 P1 功能性缺陷与 3 项 P2 缺陷，需修复后才具备生产可用性。**

| 判定 | 数量 | 说明 |
|---|---|---|
| 实测通过环节 | 12 | 见 §4 |
| P1 缺陷（影响正确性/安全） | 2 | 已删文档仍可召回；Agent 多库工具串库 |
| P2 缺陷（影响可靠性/可维护性） | 4 | 删除不级联、删除后不可清理、异常吞没、工具无兜底 |
| P3 观察项 | 3 | 分块重叠失效、重复文档占满 top-k、接口语义 |
| 未覆盖项 | 1 | 精排（权重未随部署准备） |

一句话结论：**当前代码在主流程上可用，但在「删除」语义与「多知识库绑定」两处存在明确缺陷，属于必须在生产启用前修复的问题。**

---

## 2. 验证方法与边界

### 2.1 分层验证设计

| 层 | 目的 | 是否写入业务数据 |
|---|---|---|
| T1 离线单测 | 验证 RAG 相关模块的代码级正确性 | 否 |
| T2 真实检索链路评测 | 验证 embedding → 召回 → 指标口径的端到端可用性与可复现性 | 否 |
| T3 业务全链路 E2E | 验证入库 + 检索的真实业务流程 | **是**（临时知识库，测后回收） |
| T4 Agent 衔接 | 验证 RAG 与 Agent 工具层的对接 | 否 |

### 2.2 一致性前提（已校验）

容器内 `app/services/knowledge.py`、`app/core/vector_db.py`、`app/utils/document.py` 的 sha256 与工作区**逐字节一致**，容器镜像构建时间为当日，因此本轮结论可直接指向当前代码。

| 文件 | 容器内 sha256 |
|---|---|
| `app/services/knowledge.py` | `6cca9446cdad…bf327` |
| `app/core/vector_db.py` | `8c9ab2876fb5…aba0c0` |
| `app/utils/document.py` | `c9bced7f9b7b…fead45` |

---

## 3. 环境基线：两项必须先行澄清的事实

### 3.1 本机存在两套彼此独立的 MySQL（E1）

| | 连接来源 | 主机 / 端口 | 账号 | 实际数据 |
|---|---|---|---|---|
| A | `backend/.env`（本地开发） | `localhost:3306` | `studio` | tenant `1`–`4`、`67da0684…`；20 个知识库（含历史遗留） |
| B | compose 容器环境（应用实际使用） | `mysql:3306`（**未向宿主机发布端口**） | `ai_studio` | tenant `3d993ed5…`(admin)、`a5bfea7f…`(ScreenshotDemo)；2 个知识库 |

`docker port ai-studio-mysql` 返回空，证明容器 MySQL 未映射到宿主机端口，因此 `localhost:3306` 是另一实例。

**影响**：用本地配置探测「线上数据」，会得到与事实完全相反的结论。本轮首轮勘察即因此误判「知识库与 Qdrant 集合失联」，实际二者在库 B 中是**匹配**的（`kb_aa42da04`↔0 点，`kb_e5dd6706`↔602 点）。**后续一切以库 B 为准。**

### 3.2 本地 venv 缺少默认向量化依赖（E2）

`requirements.txt` 声明了 `sentence-transformers==3.3.1` 与 `torch==2.6.0+cpu`，但这两个包**仅存在于容器镜像内**，未安装进 `backend/.venv`。

**影响**：本地无法运行任何真实 embedding / 精排链路；本地单测出现 3 个失败 + 1 个跳过（全部由该缺口造成）。故 T1 与 T2 改在容器内执行。

### 3.3 精排权重未随部署准备（E3）

容器 HF 缓存卷仅含 `models--BAAI--bge-base-zh-v1.5`，**不含 `BAAI/bge-reranker-v2-m3`**。在生产参数（`HF_HUB_OFFLINE=1`）下实测：

```
reranker 不可用: RerankerUnavailable
failed to load reranker BAAI/bge-reranker-v2-m3:
  We couldn't connect to 'https://huggingface.co' to load the files,
  and couldn't find them in the cached files.
```

即：**一旦把 `RERANKER_ENABLED` 置为 true，精排不会生效**。当前 `reranker_enabled=False` 为默认值，故不影响主链路；且 `_apply_rerank` 正确捕获 `RerankerUnavailable` 并回落稠密排序（降级路径设计正确）。

**建议**：若要启用精排，必须先把权重建入 `hf-cache` 卷，并与 `docs/rag-eval/EVALUATION-REPORT.md` §6 的延迟结论（本机 `candidate_k=20` 约 7–13 s/查询）一并评估。

---

## 4. 逐环节实测结果

### T1 离线单测（容器内）

```
184 passed, 1 xfailed, 0 failed in 18.04s
```

对照：同一批用例在本机 venv 为 `180 passed, 3 failed, 1 skipped, 1 xfailed`，3 个失败全部位于 `tests/test_reranker.py::TestFailureDegradation`，根因即 E2。

| 项 | 结果 |
|---|---|
| 通过 | 184 |
| 失败 | 0 |
| xfail（已知缺陷 D11） | 1 |

### T2 真实检索链路评测（容器内，只读）

命令：

```bash
docker exec ai-studio-backend sh -c 'cd /app && HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python scripts/rag_eval.py --retriever qdrant --index-dir data/rag_eval --name verify-e2e --k 1,3,5,10'
```

| 指标 | @1 | @3 | @5 | @10 |
|---|---|---|---|---|
| RECALL | 0.7100 | 0.8167 | **0.8667** | **0.8900** |
| HIT | 0.8100 | 0.8500 | 0.8900 | 0.9100 |
| MRR | 0.8100 | 0.8300 | 0.8390 | **0.8423** |
| NDCG | 0.8100 | 0.8081 | 0.8294 | **0.8381** |
| MAP | 0.7100 | 0.7933 | 0.8068 | 0.8116 |

- 查询数 100，失败 0。
- 召回延迟 p50 = **104.59 ms**、p95 = **158.24 ms**（容器 CPU；对照 9-12 的 MPS 基线 61.4/84.0 ms，差异符合设备预期）。
- **结论：全部指标与 `EVALUATION-REPORT.md`（2026-09-12 基线）逐位一致**，说明 embedding 模型、`search_points` 召回实现、段落映射与指标计算四段链路真实可用且可复现。这条一致性同时验证了「评测口径与线上口径未分叉」的设计约束仍然成立。

### T3 业务全链路 E2E（写入，测后回收）

执行路径：`建库 → 上传 → Celery 异步处理 → 分块落库 → 向量入库 → 检索 → 清理`

| 步骤 | 接口 | 实测结果 |
|---|---|---|
| 0 | `POST /knowledge-bases/{已有库}/search` | 200；3/3 查询命中，top1 score 0.6121 / 0.6857，片段语义正确 |
| 1 | `POST /knowledge-bases` | 200；`embedding_model=BAAI/bge-base-zh-v1.5` |
| 2 | `POST /knowledge-bases/{id}/documents/upload` | 200 |
| 3 | `GET /documents/{id}` 轮询 | `pending → processing → completed`，**约 12 s 完成** |
| 3b | `GET /documents/{id}/chunks` | 200；`total=1`（短文档未触发切分，符合 `chunk_size=1024` 预期） |
| 4 | `POST /knowledge-bases/{id}/search` | 200；3/3 查询命中且返回片段与上传内容一致 |
| 5 | `DELETE /documents/{id}` → `DELETE /knowledge-bases/{id}` | 均 200 |

**关键结论**：入库侧「上传 → 异步解析 → 向量化 → 双写 MySQL/Qdrant」与检索侧「查询向量化 → 召回 → 回表组装」两段均真实贯通，异步任务由容器内 Celery worker 正常消费，无卡死。

### T4 Agent 知识库工具衔接（只读，不调用 LLM）

对 `AgentService._build_langchain_tools()` 构造的知识库工具直接调用其 `func`：

| 用例 | 输入 | 结果 |
|---|---|---|
| A 绑定真实库（602 向量） | `"注意力机制"` | **OK，返回 2562 字符真实分块内容** |
| B 绑定不存在的库 | `"注意力机制"` | `NotFoundException` 直接抛出（无兜底） |
| C 同时绑定「不存在的库」+「真实库」 | `"注意力机制"` | **两个工具均返回 2562 字符、内容完全相同** → 串库 |
| D 检索明细 | `"注意力机制"` | hit0/hit1 同分同内容（重复文档），hit2 相关 |
| E 空白查询 | `"   "` | `ValidationException`（输入校验正常） |

**结论**：RAG 与 Agent 工具的衔接**功能上可用**（用例 A 返回真实检索内容）；但存在 **P1 串库缺陷**（用例 C）与 **P2 无兜底缺陷**（用例 B），详见 §5。

---

## 5. 缺陷清单

> ### 状态回写（2026-09-15）
>
> 下表为各缺陷的**最新处置状态**，正文小节保留的是**发现时**的描述，未逐条改写。
> 逐项改动、前后指标与复现命令见 [FIX-AND-HYBRID-RETRIEVAL-REPORT.md](./FIX-AND-HYBRID-RETRIEVAL-REPORT.md)。
>
> | 编号 | 缺陷 | 状态 | 处置要点 |
> |---|---|---|---|
> | P1-A | 已软删文档的分块仍被检索命中 | ✅ 已修复 | 回表新增文档级 `deleted_at` 过滤 |
> | P1-B | Agent 知识库工具闭包晚绑定致串库 | ✅ 已修复 | 闭包默认参数绑定修复 + 回归用例 |
> | P2-C | 删除知识库不级联清理文档/分块/向量 | ✅ 已修复 | 级联顺序固定，限同租户；删库失败仅记日志不抛错 |
> | P2-D | 知识库删除后其文档进入「不可清理」状态 | ✅ 已修复 | 允许在库已删的情况下单独清理文档 |
> | P2-E | `search()` 吞掉 Qdrant 异常，故障与空结果不可区分 | ✅ 已修复 | 记录 warning 日志 + 返回结构化诊断（对外契约不变） |
> | P2-F | knowledge 工具无异常兜底 | ✅ 已修复 | 工具层兜底，不回传栈信息 |
> | P3-G | `chunk_overlap` 未生效（D11） | ✅ 已修复 | 改标准回溯合并，实测重叠 119~125 字符；**并据 512 token 上限把分块参数由 1024/128 重新标定为 448/64** |
> | P3-H | 检索结果无文档级去重 | ✅ 已修复 | 默认开启内容等值折叠 + 超额召回补偿（`retrieval_fetch_multiplier`） |
> | P3-I | 存量数据不一致 | ✅ 已对齐 | 计数漂移修复 + 集合作用域闸门；**并拦下一处会误删 28771 个评测向量的隐患** |
>
> **未闭合项**（不属上表范围，登记于报告 §7）：D12 元数据（`heading_path`/页码）、
> 精排权重未随容器缓存准备（E3）、以及**分块参数变更后的向量索引重建**（需决策，见报告 §3.6）。

### P1-A｜已软删除文档的分块仍会被检索命中

- **位置**：`app/services/knowledge.py:337-357`（`search()` 回表组装）；`app/repositories/knowledge.py`（`list_by_vector_ids`）
- **现状**：`search()` 仅通过 `list_by_vector_ids` 过滤**分块级** `deleted_at IS NULL`，**未对所属文档的 `deleted_at` 做任何判定**。
- **实测证据**：对知识库 `kb_e5dd6706…`（「大模型」）检索 `"注意力机制"`，返回 top-10；其中包含：

  ```
  doc=4626a81d-60bd-473c-92ba-443eacd144f7  name=Happy-LLM-0727.pdf  文档已删=True
  ```

  该文档 `deleted_at=2026-09-11 23:37:48`，其 301 个分块至今仍为未删状态。进一步验证回表路径：

  ```
  list_by_vector_ids(已删文档的 3 个 vector_id) → 返回 3 条
    其中「所属文档已软删」的分块数：3
  ```

- **影响**：已下架/已删除的文档内容仍会被检索返回给 Agent 与前端，属于**内容下架失效**。
- **成因说明**：写入侧（`delete_document`）已实现级联软删分块（D9 处置），但
  1. **读取侧缺少防御**——对任何未级联的历史数据或异常路径完全无保护；
  2. 现存该批数据（删除于 2026-09-11，早于 D9 修复）即长期处于「文档已删、分块存活、向量在库」状态。
- **建议修复**：在回表查询上 join `knowledge_documents` 并追加 `document.deleted_at IS NULL`（或在 `list_by_vector_ids` 内实现），使读取侧不依赖写入侧的正确性。

### P1-B｜Agent 知识库工具闭包晚绑定导致串库

- **位置**：`app/services/agent.py:341-359`
- **现状**：

  ```python
  if tool_type == "knowledge":
      kb_id = config.get("knowledge_base_id")     # 循环内赋值，函数作用域共享
      top_k = config.get("top_k", 5)
      def knowledge_search_func(query: str) -> str:
          results = kb_service.search(kb_id=kb_id, query=query, top_k=top_k)  # 晚绑定
  ```

  `kb_id` / `top_k` 是 `_build_langchain_tools` 的函数级局部变量，闭包捕获的是**同一个 cell**，循环结束后取最后一个值。同文件的 `api` / `function` / `workflow` 分支均已用默认参数绑定（`_url=url` 等），**唯 knowledge 分支遗漏**。
- **实测证据**：同时绑定「不存在的库」与「真实库」两个知识库工具：

  ```
  tool_missing → OK，长度=2562
  tool_full    → OK，长度=2562
  判定：闭包晚绑定【存在】
  ```

  绑定到不存在知识库的工具，实际检索了最后一个知识库并成功返回内容。
- **影响**：一个 Agent 绑定多个知识库时，**所有知识库工具都只查最后一个库**，其余库永远不被检索，且不报错——静默的功能失效。
- **建议修复**：改为 `def knowledge_search_func(query: str, _kb_id=kb_id, _top_k=top_k)` 并用 `_kb_id` / `_top_k`，与同文件其它分支保持一致。

### P2-C｜删除知识库不级联清理文档、分块与向量

- **位置**：`app/services/knowledge.py:123-127`（`delete_knowledge_base`）
- **现状**：仅执行 `kb_repo.update(kb, deleted_at=...)`，不触碰 `knowledge_documents`、`knowledge_chunks`，也不删除 Qdrant 集合。
- **实测证据**：`DELETE /knowledge-bases/{id}` 返回 200 后：

  | 检查 | 结果 |
  |---|---|
  | `GET /knowledge-bases/{id}` | 404（库已软删，符合预期） |
  | `GET /documents/{doc_id}` | **200，status=completed**（未级联） |
  | `GET /documents/{doc_id}/chunks` | **total=1**（未级联） |
  | Qdrant `kb_{id}` | **仍存在，points=1**（向量残留） |

- **影响**：知识库删除后，MySQL 残留文档与分块行，Qdrant 集合与向量**永久残留**（存储泄漏），与 `delete_document` 的完整级联形成明显不对称。
- **建议修复**：`delete_knowledge_base` 内按文档批量调用级联清理并删除集合；或引入统一的「资源回收」路径。

### P2-D｜知识库删除后，其文档进入「不可清理」状态

- **位置**：`app/services/knowledge.py:210-221`（`delete_document` 首行 `self.get_knowledge_base(doc.kb_id)`）
- **现状**：`delete_document` 先校验知识库存在，而 `get_knowledge_base` 会过滤已软删记录。
- **实测证据**：在知识库已软删的前提下删除其文档：

  ```
  DELETE /knowledge/documents/{doc_id}
  → 404 {"code":404,"message":"KnowledgeBase not found (id=9375f3cb-…)","error_code":"NOT_FOUND"}
  ```

- **影响**：这是 P2-C 的**放大效应**——一旦库被删除，其残留文档与向量**无法再通过任何接口清理**，只能人工介入数据库与 Qdrant。
- **建议修复**：在 `delete_document` 中放宽知识库校验（按 `doc.kb_id` 直接定位，不要求库可见），或在 P2-C 中一次性完成级联。

### P2-E｜`search()` 吞掉 Qdrant 异常，故障与空结果不可区分

- **位置**：`app/services/knowledge.py:322-332`
- **现状**：Qdrant 调用异常被捕获后 `logger.warning` + `return []`。
- **影响**：集合缺失、Qdrant 宕机与「确实没有相关内容」在调用侧返回完全一致的结果。本轮首轮勘察即因该设计把「集合不存在」误读为「库里没有向量」。
- **建议修复**：返回结构化结果（如 `{"results": [], "degraded": true, "reason": ...}`）或在响应头/日志中携带可判定标识；同时保留降级不中断的行为。

### P2-F｜knowledge 工具无异常兜底，错误直接穿透到 Agent

- **位置**：`app/services/agent.py:346-351`
- **实测证据**：绑定不存在的知识库时，工具 `func` 抛出 `NotFoundException`（未被捕获）。
- **影响**：LangChain `Tool` 默认不吞异常，工具报错会中断 ReAct 执行；同时暴露内部异常信息。与 `search()` 内部「宽容降级」的设计取向不一致（同文件 `api` 分支有 try/except 包裹）。
- **建议修复**：工具内 try/except，转为可读的失败说明文本返回给模型。

### P3-G｜`chunk_overlap` 未生效（D11，已知）

`TextSplitter._merge_splits`（`app/utils/document.py:157-174`）长度比较为 `len(current) + len(s) + separator_len`，**从未纳入 `chunk_overlap`**，声明的 128 字符重叠实际为 0。已有 `tests/test_text_splitter.py` 以 `xfail` 固化（本轮 T1 复现该 xfail）。后果：跨块边界的答案被一分为二，压低 Recall 上限。

### P3-H｜检索结果无文档级去重，重复文档会占满 top-k

实测 `search()` 返回：

```
hit0: score=0.5978 retrieval=0.5978 idx=30
hit1: score=0.5978 retrieval=0.5978 idx=30   ← 同分同内容，来自另一份重复文档
```

知识库内存在内容重复的多份文档时，同一段落的多个副本会同时占据 top-k，挤压其它段落的召回机会。建议在结果组装层增加按内容/文档的去重或多样性控制。

### P3-I｜存量数据不一致（历史遗留，非当前代码缺陷）

知识库 `kb_e5dd6706…` 的文档/分块/向量三方统计：

| 文档 | 文档 deleted_at | `doc.chunk_count` | 分块行数 | 未删分块 |
|---|---|---|---|---|
| `4626a81d…` | 2026-09-11 23:37:48 | 301 | 301 | **301** ← 未级联 |
| `9de3b61e…` | 2026-09-14 09:44:11 | 301 | 301 | 0 |
| `bfcaa9d3…` | 2026-09-11 09:48:39 | 301 | 301 | 0 |
| `d93f26c1…` | —（存活） | 301 | 301 | 301 |

| 口径 | 值 | 说明 |
|---|---|---|
| MySQL 分块行总数 | **1204** | 4 份重复上传的同一 PDF |
| MySQL 未删分块 | **602** | |
| `kb.chunk_count` | **602** | 与未删分块一致 |
| `doc.chunk_count` 之和 | **1204** | 与 `kb.chunk_count` 不符 |
| Qdrant 实际点数 | **602** | 仅 2 份文档的向量在库 |

三方对不上，且 `4626a81d` 的「文档已删 / 分块存活 / 向量在库」正是 P1-A 的成因数据。删除时间早于 D9 修复，故判定为**存量脏数据**，但配合 P1-A 会产生实际的内容泄漏。**建议**：修复 P1-A 后，用一次性脚本对齐存量（软删 `4626a81d` 的存活分块并清理其向量），并校正 `doc.chunk_count`。

---

## 6. 未覆盖项与限制

| 项 | 状态 | 原因 |
|---|---|---|
| 精排（CrossEncoder）真实推理 | **未覆盖** | E3：权重未随部署准备，离线加载失败。精排相关逻辑由 T1 的 `test_reranker.py`（容器内通过）覆盖 |
| 完整 Agent 对话（含 LLM 推理） | **未覆盖** | 现有 Agent「超级旅游助手」未绑定任何工具（`agent_tools` 为 0）；且调用外部 DeepSeek API 会产生额度消耗。RAG→工具 的衔接已改用直接调用工具 `func` 的方式验证（T4） |
| 混合检索 / 稀疏召回 | 不适用 | 属 Phase 5 范围，尚未实现 |
| 多租户隔离下的跨租户检索 | 已间接验证 | T4 用例 B 中，跨租户知识库 id 返回 `NotFoundException`，隔离生效 |
| 并发/压测 | 未覆盖 | 本轮目标为「流程能否走通」，非性能验证 |

**测试数据处置**：本轮创建 2 个临时知识库（`rag-e2e-probe-*`、`rag-del-path-*`）与 2 份探针文档，均已软删除回收；Qdrant 临时集合（`kb_614d8098…`、`kb_9375f3cb…`）已删除。**Qdrant 集合已恢复至初始的 3 个**（`kb_rageval_t2r` 28771 / `kb_e5dd6706…` 602 / `kb_aa42da04…` 0）。其中 `rag-del-path` 的探针文档因 P2-D 缺陷无法通过接口删除，已改用定向 SQL 回收；知识库 2 条软删记录与 `chunk_count` 计数按现有实现保留。**知识库「大模型」「企业产品知识库」及其数据未被修改。**

---

## 7. 修复优先级建议

| 序 | 项 | 级别 | 理由 |
|---|---|---|---|
| 1 | P1-A 读取侧文档级删除过滤 | P1 | 内容下架失效，直接影响合规与业务正确性 |
| 2 | P1-B knowledge 工具闭包绑定 | P1 | 静默功能失效，排查成本高 |
| 3 | P2-D 文档可清理性 | P2 | 阻断故障恢复，是 P2-C 的放大器 |
| 4 | P2-C 删除知识库级联 | P2 | 存储泄漏与数据残留 |
| 5 | P2-F 工具异常兜底 | P2 | 影响 Agent 稳定性与错误可读性 |
| 6 | P2-E 检索异常可观测性 | P2 | 影响故障定位效率 |
| 7 | P3-I 存量数据对齐 | P3 | 配合第 1 项产生实际泄漏，建议同步处理 |
| 8 | P3-G / P3-H | P3 | 已纳入既有计划（Phase 5）/ 需评估是否引入去重 |

---

## 8. 附录：复现命令

```bash
# T1 离线单测（容器内）
docker exec ai-studio-backend sh -c 'cd /app && python -m pytest \
  tests/test_rag_metrics.py tests/test_rag_eval_dataset.py tests/test_rag_eval_merge.py \
  tests/test_rag_eval_runner.py tests/test_rag_eval_cli.py tests/test_rag_passage_mapping.py \
  tests/test_text_splitter.py tests/test_reranker.py tests/test_vector_db.py \
  tests/test_vector_db_collection.py tests/test_embedding.py tests/test_embedding_client.py \
  tests/test_knowledge_service_signature.py tests/test_knowledge_vector_delete.py \
  tests/test_knowledge_search_rerank.py -q --basetemp=/tmp/pytest-rag'

# T2 真实检索链路评测（容器内，只读）
docker exec ai-studio-backend sh -c 'cd /app && HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python scripts/rag_eval.py --retriever qdrant --index-dir data/rag_eval \
  --name verify-e2e --out-dir /tmp/rag-reports --k 1,3,5,10'

# T3/T4 端到端脚本（宿主机，需从根 .env 取 JWT_SECRET_KEY、从容器环境取账号）
#   见本仓库 .workbuddy/scratch/rag_e2e.py / check_agent_rag.py / check_read_path.py
# 注意：Docker 部署的接口前缀为根路径（/knowledge/...），
#       OpenAPI 中的 servers: /api 仅为文档与 Nginx 反代元数据。
```
