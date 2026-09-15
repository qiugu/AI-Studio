# 检索结果重复与页面滚动缺失修复报告

> 触发来源：语义检索页面实测反馈 —— ① 10 条检索结果中约一半内容重复；② 结果过长时页面无滚动条，布局被结果列表撑破。
>
> 关联文档：[plan-knowledge-retrieval-p0-p2.md](plan-knowledge-retrieval-p0-p2.md)、[rag-eval/E2E-VERIFICATION-REPORT.md](rag-eval/E2E-VERIFICATION-REPORT.md)

---

## 1. 结论摘要

两个问题分属不同层，**没有共同根因**：

| 问题 | 层级 | 一句话根因 |
|---|---|---|
| 结果重复 | 数据层 + 检索层叠加 | 同一份文档被重复上传产生多份互不覆盖的向量，且检索层完全没有内容去重 |
| 无滚动条 / 布局被撑破 | 前端 app shell | 全局 CSS 覆盖掉了 antd 的 `min-height: 0`，使内层 Layout 无法收缩；同时 `Content` 不承担滚动 |

问题一中的「重复文档」现象此前已作为 **P3-H / P3-I** 记录在 E2E 验证报告中，本次是它在 UI 层的显性化，并非新缺陷；问题二是本次新定位的缺陷。

---

## 2. 问题一：检索结果重复

### 2.1 根因链路

| 层 | 位置 | 缺陷 |
|---|---|---|
| 数据层 | `services/knowledge.py` `upload_document` | 无任何重复校验（文件名 / 大小 / 内容哈希均不查），同一份 PDF 反复上传即产生 N 条文档记录 |
| 向量层 | `services/knowledge_processor.py:70` | `vector_id = uuid5(NAMESPACE_DNS, f"{doc.id}_{index}")` **把 `doc.id` 纳入命名空间**，因此同名同内容的副本生成**不同** point id，`upsert` 互不覆盖，Qdrant 内并存 N 份等值向量 |
| 检索层 | `services/knowledge.py` `search()` | 只做「按 `vector_id` 回表 → 排序 → 截断 `top_k`」，**无内容去重**；`reranker_enabled` 默认 `False` 时 `fetch_k = top_k`，等值副本必然占满 top-k |
| 前端 | `KnowledgeDetail.tsx` | `List` 直接渲染响应，无去重；`List.Item` 还缺 `key` |

### 2.2 截图现象的判读依据

截图中 `分块 #100 / #5 / #108` 各出现两次，且相似度**逐位相同**（64.7% / 63.9% / 63.3%）。这正是「同内容 → 同 embedding → 同分数，但 point id 不同 → 各占一个候选位」的典型特征：若是同一 point 被渲染两次，分数相同但 id 相同；若是分块重叠导致的近似重复，分数不会逐位相同。

存量数据实测（E2E 报告 P3-I）：该知识库有 **4 份重复上传的同一 PDF**，其中 2 份存活 → MySQL 1204 行分块、Qdrant 602 点。

### 2.3 影响面不止界面

`services/agent.py` 的 knowledge 工具同样调用 `search()`，重复片段会被**重复灌入 LLM 上下文**——既浪费 token，又稀释有效信息密度。因此修复必须落在服务层，而非前端过滤。

---

## 3. 问题二：无滚动条与布局被撑破

### 3.1 根因链路

| # | 位置 | 缺陷 |
|---|---|---|
| 1 | `src/styles/global.css` | 全局 `.ant-layout { min-height: 100vh }` 同时命中 `AppLayout` 中**嵌套的内层** `<Layout>`，**覆盖掉 antd 自带的 `min-height: 0`**，使其无法收缩到 100vh 以下 |
| 2 | `components/Layout/AppLayout.tsx` | 内层已含 64px `Header`，被锁死 100vh 后内容变长即整体超过外层 `h-screen`，溢出部分穿出外壳 |
| 3 | `components/Layout/AppLayout.tsx` | `<Content>` **未设 `overflow`**：antd 的 `.ant-layout-content` 仅有 `flex: auto` + `min-height: 0`，只保证自身被压缩，**不负责处置溢出的子内容**；溢出为 `visible` 既不滚动也不裁剪 |
| 4 | 结果 | 滚动归属不明：既非 Content 滚动，也非文档滚动 → 无滚动条，且 Header / Sider 的视觉结构被一起顶乱 |

### 3.2 为什么必须同时修 1 和 3

两者解决的是不同问题，缺一不可：

* 只加 `overflow: auto`：内层 Layout 仍被 `min-height: 100vh` 锁死，溢出发生在假想的 100vh 高度里，滚动条会出现在一个比视口更高的容器上，Header 依然会被顶走；
* 只删全局规则：`Content` 不再溢出穿出，但也没有滚动条，长内容会被直接裁掉不可达。

---

## 4. 修复内容

### 4.1 后端

| 文件 | 改动 | 理由 |
|---|---|---|
| `app/core/config.py` | 新增 `retrieval_dedup_enabled = True`、`retrieval_fetch_multiplier = 2` | 去重可开关（便于对照回归），倍数可调（权衡延迟） |
| `app/services/knowledge.py` `search()` | 去重开启时 `fetch_k = max(fetch_k, top_k × multiplier)` | 折叠会减少候选，必须超额召回补回坑位 |
| `app/services/knowledge.py` `_dedupe_by_content`（新增） | 按内容归一化折叠等值副本，保留最高分者，记录 `duplicate_count` | 检索层兜底：对**存量**重复数据立即生效 |
| `app/services/knowledge.py` `upload_document` | 同库「同名 + 同大小」命中未删文档即抛 `ValidationException`，消息含已有文档 ID 与处置建议 | 堵源头：检索层去重治不了新产生的重复 |

**两个关键设计取舍：**

1. **折叠发生在精排之前。** 否则精排的候选预算会被等值副本吃掉，且会对同一段落反复推理，属纯浪费算力。
2. **归一化只做空白处理，不做大小写折叠。** 中文正文的差异几乎都来自分块边界的空白；而大小写折叠会把 `Transformer` 与 `transformer` 这类在代码语境下可能确有区别的片段误判为同一段，属过度合并。

### 4.2 前端

| 文件 | 改动 | 理由 |
|---|---|---|
| `src/styles/global.css` | 删除全局 `.ant-layout { min-height: 100vh }`，改为说明性注释 | 高度收敛职责交还给外层 `h-screen` |
| `components/Layout/AppLayout.tsx` | `Content` 加 `overflow-auto`，并补全高度契约注释 | 让 `Content` 成为唯一滚动容器 |
| `pages/Workflows/WorkflowEditor.css` | `.workflow-editor-container` 由 `height: 100vh` 改为 `height: 100%` | 100vh 比可用空间高出整整一个 Header，会留下无意义滚动条；与 `AgentChat.css` 的既有策略保持一致 |
| `pages/Knowledge/KnowledgeDetail.tsx` | `List.Item` 补 `key`；展示已折叠副本数；失败提示透出后端文案；`top_k` 提为具名常量 | 让「结果条数少于 N」可解释；消除 React key 告警；避免重复弹窗 |
| `types/knowledge.ts` / `api/knowledge.ts` | `SearchResult` 增加可选 `duplicate_count`；`uploadDocument` 支持 `_suppressErrorMessage` | 支撑上述两点 |

---

## 5. 验证证据

### 5.1 单元测试

新增两个测试文件，共 **14 个用例**；另在既有精排测试文件中把 1 个用例改写为 2 个（拆分「去重关闭的等价基线」与「去重开启的放大召回」）。

| 文件 | 覆盖 |
|---|---|
| `tests/test_knowledge_search_dedup.py`（新增，10 例） | 副本折叠、保留最高分、空白归一化生效、**大小写不合并**、`duplicate_count` 语义、顺序单调、超额召回补足、倍数=1 降级、不足 top_k 不虚报、关闭去重的对照通路、**折叠先于精排** |
| `tests/test_knowledge_upload_dedup.py`（新增，4 例） | 同名同大小被拒且消息可执行、**拒绝发生在任何写入之前**、首次上传放行并派发任务、固化判定键为 (kb_id, file_name, file_size) |

```
$ .venv/bin/python -m pytest -q --basetemp=.pytest-tmp
3 failed, 379 passed, 1 skipped, 1 xfailed in 41.28s
```

* 3 处失败全部为 `tests/test_reranker.py::TestFailureDegradation::*`，原因是在测试体内 `import sentence_transformers` 抛 `ModuleNotFoundError`（本机未安装该可选依赖），**与本次改动无关**；
* 1 处 skip 同为缺少 `torch / sentence-transformers`；
* 1 处 xfail 为已登记的 D11（`chunk_overlap` 未生效）。

> 注意：`--basetemp` 必须指向工作区内目录。用系统临时目录时会触发沙箱的批量删除守卫，pytest 在清理临时目录时以 `SystemExit` 中断，表现为大量 `ERROR at setup`——那是环境问题，不是用例失败。

### 5.2 静态检查

```
$ npx eslint src/api/knowledge.ts src/components/Layout/AppLayout.tsx \
               src/pages/Knowledge/KnowledgeDetail.tsx src/types/knowledge.ts
✖ 4 problems (3 errors, 1 warning)
```

4 项全部落在 `KnowledgeDetail.tsx` 第 65–92 行（`loadDocuments` 先使用后声明 + `useEffect` 依赖告警），**均为本次未触碰的既有代码**；其余三个改动文件零问题。

```
$ npx tsc -b
exit=0
```

### 5.3 契约变更说明

本次**有意修改**了既有用例的断言，需在评审时确认：

| 用例 | 原断言 | 现断言 | 原因 |
|---|---|---|---|
| `test_default_queries_only_top_k` | 默认只查 `top_k` 条 | 拆为两个：关闭去重时 `limit == top_k`（等价基线）；开启去重时 `limit == top_k × multiplier` | 默认行为已变更，等价路径需显式保留 |
| `test_explicit_false_overrides_enabled_config` | `limit == 2` | 关闭去重后仍 `limit == 2` | 隔离「显式入参覆盖配置」这一单一意图 |
| `test_candidate_k_never_below_top_k` | `limit == 4` | 关闭去重后仍 `limit == 4` | 同上，避免与超额召回断言混在一起 |

---

## 6. 已知局限与未做项

| 项 | 状态 | 说明 |
|---|---|---|
| 改名重传同一份文件 | **未覆盖** | 判定键仅 (kb_id, file_name, file_size)。要覆盖需新增内容哈希列并配套迁移，属独立提案 |
| 存量重复文档清理（P3-I） | **未执行** | 需一次性脚本软删重复文档并清理 Qdrant 向量、校正 `doc.chunk_count` / `kb.chunk_count`。**当前库中重复文档仍占用存储与向量空间，但检索结果已不再重复** |
| 近重复内容 | **不折叠** | 仅折叠空白归一化后完全一致的内容。页码/页眉差异造成的近似重复需相似度聚类，属召回策略范畴 |
| 单文档多样性上限 | **未实现** | 原 P4 提案。当前同一文档的**不同**分块仍可占满 top-k，需在评测集上标定配额 |
| `kb.chunk_count` 计数膨胀 | **未修** | `knowledge_processor` 累加而非重算，重复上传会持续虚高 |

---

## 7. 待人工确认（无法在无后端环境自动验证）

本次改动涉及全局样式，以下项建议在可用环境实机确认：

1. **知识库语义检索页**：长结果下出现 Content 内滚动条，Header 与 Sider 不位移；重复库检索时结果条数 ≤ 10 且无重复，并出现折叠提示；
2. **Workflow 编辑器**：React Flow 画布应刚好填满 Content，无多余滚动条（`height: 100%` 是否按预期解析）；
3. **Agent 对话页**：`.agent-chat-container { height: 100% }` 依赖 Content 具有确定高度，需确认消息区滚动行为未变；
4. **上传重复文档**：应弹出后端的具体拒绝文案（单条提示，而非两条）。

---

## 8. 配置项

两个新开关均通过 `BaseSettings` 自动读取环境变量，无需改动 `.env.example` 结构：

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `RETRIEVAL_DEDUP_ENABLED` | `true` | 关闭后检索行为与改造前**严格等价**，用于对照排查 |
| `RETRIEVAL_FETCH_MULTIPLIER` | `2` | 去重前的召回放大倍数。调高可提升去重后的结果条数，代价是 Qdrant 召回量与回表行数线性上升；设为 `1` 等价于「只去重不补坑位」 |

---

## 9. 存量重复文档核查结论（2026-09-14 22:20 实测）

**结论：存活数据层已无重复——同一份 PDF 的 4 次上传中 3 份已软删，仅 1 份存活；向量层无任何软删文档的残留 point，三方计数完全对齐。但这不是本方案 P3 清理脚本的产物（该脚本未执行），而是「删除文档 → 级联清分块 + 清向量」的既有能力产生的副产物。**

### 9.1 三层一致性核对（直连容器内 MySQL 与 Qdrant）

| 层 | 观测项 | 实测值 | 判定 |
|---|---|---|---|
| MySQL 文档 | `knowledge_documents` 中同一 KB 的重复组 `(kb_id,file_name,file_size)` | 仅 1 组：`Happy-LLM-0727.pdf`（20717304 B）×4，`alive = 1` | 存活集合内 **无重复** |
| MySQL 分块 | `knowledge_chunks` 按 doc 聚合 | 存活 301 行（唯一归属 `d93f26c1…`）；软删 905 行 | 软删留痕，不影响检索 |
| MySQL 计数 | `kb.chunk_count` | 301 | 与向量层 **一致** |
| Qdrant | `kb_e5dd6706…` `points_count` | 301，scroll 全量后 **100%** 归属存活 doc `d93f26c1…` | **零孤儿向量** |

> 上一轮记录的 `602 点 / 1204 行` 与 `kb.chunk_count` 三方不一致已消除。

### 9.2 端到端实测（真实 HTTP 请求，非代码推断）

1. **检索接口**：`POST /knowledge/knowledge-bases/{kb_id}/search?query=…&top_k=10&score_threshold=0.3` → HTTP 200，返回 10 条，`chunk_index` 互不相同（223/127/210/59/108/168/267/228/200/1），无重复键。响应中已含新增字段 `duplicate_count`（均为 0），**证明去重改造代码已在运行容器内生效**（容器与工作区 `knowledge.py`、`config.py` 的 sha256 逐位一致）。
2. **上传拦截**：以同一份 PDF（同文件名、同字节数）再次上传 → **HTTP 422**，返回 `知识库中已存在同名同大小的文档「Happy-LLM-0727.pdf」（文档 ID: d93f26c1…），已拒绝重复上传。拒绝路径未落库、未留临时文件（`uploads` 卷文件数仍为 6，无 `tmp*`）。**防复发机制实测有效。**

### 9.3 唯一残留（不影响检索，影响存储）

| 残留 | 规模 | 影响 |
|---|---|---|
| 软删文档行 | 3 行 | 无（回表有 `deleted_at IS NULL` 过滤） |
| 软删分块行 | 905 行 / 约 0.64 MB 文本 | 无 |
| **软删文档的上传原件** | 3 份 × 20.7 MB ≈ **62 MB**（`ai-studio_uploads` 卷） | **磁盘占用真实存在**：`delete_document` 只软删记录与分块，**不删除已落盘的源文件** |

如确需回收这 62 MB，需按文档 ID 定向删除 `uploads/<tenant>/<kb>/<doc_id>/` 目录。**注意 `delete_document` 的软删语义意味着该残留会随每次「删除后重传」线性增长**，是否补一个「硬删附件」的清理动作（或改为删除时同步 unlink）建议单独提提案——它涉及「软删可恢复」与「磁盘可回收」的语义取舍，不宜夹带在本次修复中。
