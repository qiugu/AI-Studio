# Phase 5 统一重索引方案（5.4 元数据 + 5.6 迁移 + 5.8 重建）

> 编制日期：2026-09-15 ｜ 状态：**执行中（§5 序号 1–4、6、8 已完成；5 后台运行中；7 待其完成后）**
> 上游依据：[FIX-AND-HYBRID-RETRIEVAL-REPORT.md](./FIX-AND-HYBRID-RETRIEVAL-REPORT.md) §3（分块参数标定）、[PLAN.md](./PLAN.md) §6 Phase 5
> 适用范围：本文替代 PLAN.md 中 5.4 / 5.6 / 5.8 三项的独立排期，**合并为一次重建**
>
> **执行记录（2026-09-15）**：
>
> * §3 迁移已执行并三项验证通过（`alembic current == heads == i3j4k5l6m7n8`；新列在位、`deleted_at` 已删、代次索引已建）；905 行墓碑在删列前物理清除，dump 见 `backend/data/backups/20260915/`。
> * **用户决策落地：取消分块软删**（原方案 D 范围外追加项）。结论与论据见迁移 docstring；替代机制为 `chunk_epoch` / `active_chunk_epoch` 两列 + `vector_id` 代次后缀。
> * §4.5 业务库重建完成：635 块（448/64），已 cutover（`active_collection = kb_e5dd6706…_v2`），计数三处一致，回滚 roundtrip 实测可用。
> * §4.4 评测语料重建运行中。**吞吐修订**：实测 0.64–0.83 块/秒（非 1.4），评测重建按 **≈21 h** 计；编排入口 `scripts/run_phase5_eval_rebuild.py`，完成标记 `PHASE5-EVAL-COMPLETE`。
> * 长任务教训已固化：必须 `docker exec -d` 分离启动 + `python -u`；前台 exec 会话结束或容器重启都会杀进程。
> * 容器全量回归 623 passed / 0 failed；代码审查三问记录见实施报告附录 A。

---

## 0. 为什么必须合并成一次

分块参数已由 1024/128 改为 **448/64**（依据见实施报告 §3）。向量是**分块文本的函数**，
分块集合一变，既有向量与新块不再一一对应——**全部存量向量失效**，只能重嵌入。

于是三个目标在同一时刻集中到同一次写入上：

| 目标 | 来源 | 若分开做会怎样 |
|---|---|---|
| 块粒度按新参数 | 分块标定 | — |
| 命名稠密 + 命名稀疏布局 | 混合检索（5.3/5.7 已完成） | 先按旧分块回填混合布局，再按新分块重建一次 → **建两次** |
| `heading_path` / 真实页码元数据 | D12（5.4） | 同上 → **建两次** |

**结论**：既然重嵌入不可避免，就把元数据与混合布局在同一次写入里一起落位。
`scripts/backfill_hybrid_collection.py`（拷贝稠密向量、不重算）在**分块参数不变**时才是
省算力的正解；分块参数已变，它对本次重建**无省算力价值**，仅保留为「布局迁移」的备用工具。

---

## 1. 现状实测基线（2026-09-15 实测）

### 1.1 生产侧（业务库）

| 项 | 实测 |
|---|---|
| 存活知识库 | **2 个**：`e5dd6706…`（大模型，`bge-base-zh-v1.5`，768 维）、`aa42da04…`（`bge-large-zh-v1.5`，1024 维，**0 分块**） |
| 已软删知识库 | 2 个（`rag-e2e-probe-*`、`rag-del-path-*`） |
| 存活文档 | **1 个**：`Happy-LLM-0727.pdf`（19.76 MB，`COMPLETED`，`chunk_count=301`） |
| 存活分块 | **301** 行；已软删分块 **905** 行 |
| 上传原件 | 存活文档原件**在位** ✓（`md5 d1a4820c…`，路径见 `file_url`） |
| 上传卷残留 | 6 个文件 / 80 MB，其中 **4 份同一 PDF 副本 = 79 MB**（`delete_document` 不 unlink 落盘件的既有问题） |

生产文档在新旧参数下的实测（解析 6.3 s，正文 223,308 字符）：

| 配置 | 块数 | 词元上限 | 截断块 | 从未被编码的词元 |
|---|---|---|---|---|
| 1024 / 0 ← **当前索引的真实状态** | **301**（与库中 `chunk_count` 一致，反证旧索引重叠恒为 0） | 928 | **36.5%** | **14.69%** |
| 1024 / 128（D11 修复后同参数） | 311 | 928 | 38.3% | 14.45% |
| **448 / 64（新默认）** | **634** | **417** | **0%** | **0%** |

### 1.2 评测侧

| 项 | 实测 |
|---|---|
| 语料 | 20,000 段 / 16,313,241 字符 |
| 分块数 | 1024/0 → **28,771**（= 线上集合点数）；1024/128 → 29,269；**448/64 → 52,068** |
| 截断（旧） | 48.2% 块被截断 / 28.0% 词元从未编码（实施报告 §3.1） |
| 金标准 | 100 查询 / 123 相关段落 |

### 1.3 集合布局现状

| 集合 | 点数 | 布局 |
|---|---|---|
| `kb_rageval_t2r` | 28,771 | legacy_dense（1024/**0** 的历史索引，`baseline.json` 的来源） |
| `kb_rageval_t2r_hybrid` | 28,771 | hybrid（同分块，仅补了稀疏） |
| `kb_rageval_t2r_hybrid_idf` | 28,771 | hybrid（同上，IDF 版） |
| `kb_e5dd6706…` | 301 | legacy_dense |
| `kb_aa42da04…` | 0 | legacy_dense |

> 三个评测集合**都是 1024 分块**的产物，与 448/64 不可比；新索引必须另建集合，
> 且**保留旧集合**以维持「旧基线可复现」这条证据链。

### 1.4 写入链路当前的元数据缺口（D12）

| 位置 | 现状 |
|---|---|
| `KnowledgeChunk.source_page` | 列已存在（`Integer, NULL`），但入库时**硬编码 `None`**（`knowledge_processor.py`） |
| `heading_path` | **列不存在** |
| Qdrant payload | 仅 `tenant_id / kb_id / doc_id / chunk_index` |
| `search()` 返回项 | `id / content / score / doc_id / doc_name / chunk_index`（+ 稠密命中时的 `retrieval_score`），**无页码、无标题** |
| 解析器 | `DocumentParser.parse() -> str`：PDF 逐页 `extract_text()` 后 `"\n".join()`，**页码信息在拼接处被丢弃** |

### 1.5 硬件与吞吐（决定「能不能靠并行加速」）

| 项 | 实测 |
|---|---|
| 容器 | `torch 2.6.0+cpu`，`num_threads=8`，`cpu_count=8`，`NanoCpus=0` / `CpuQuota=0`（**无配额限制**） |
| 吞吐 | **1.4 块/秒**（约 140 GFLOPS，110M 参数 × 450 token，fp32） |
| 并行加速 | **不可行**：BLAS 线程已把 8 核占满，再开多进程不会提高总吞吐，只会互相抢占 |
| 宿主 MPS | **不可用**：`import transformers` 被沙箱策略拦截（`Sensitive content approval timed out`），表现为静默终止 |
| 配置现状（容器内） | `chunk_size=448` / `chunk_overlap=64` / `retrieval_sparse_avgdl=490` / **`retrieval_hybrid_enabled=False`** |

---

## 2. 5.4 元数据落位设计（D12）

### 2.1 决策点 1：页码/标题如何在分块时被携带

| 方案 | 做法 | 优缺点 |
|---|---|---|
| **A1（推荐）段内切分** | 解析器产出**分段**（Segment）列表，每段自带 `page` / `heading_path`；`TextSplitter` **在每段内**切分，元数据随之落到每个块 | 页码/标题归属**精确可断言**；不会出现「标题在上一页、正文在下一页」的混合归属；代价是页尾会出现更短的块（可量化） |
| A2 跨段合并 | 全文化后按偏移回映，块归属到**起始段** | 块数更少、边界更自然；但页码语义退化为「起始页」，且需要偏移映射，实现与测试成本更高 |

选择 A1 的理由：本项目的元数据是**给人看、给答案做引用**的（「出自第 37 页 §3.2」），
归属必须精确；且 A1 的分块结果**逐块可测**（可断言「同一块的 `page` 唯一」），
符合本项目「结论必须可复核」的一贯要求。

### 2.2 决策点 2：各格式的元数据可得性（**不猜，缺就留空**）

| 格式 | 页码 | `heading_path` | 依据 |
|---|---|---|---|
| `.pdf` | ✅ 精确（`pypdf` 逐页） | ❌ **留空** | `pypdf` 只给文本流，无版式/结构信息；用字号推断标题属**猜测**，会把噪音写进元数据。后续若要做，另立专项并以样本准确率作为验收 |
| `.md` | ❌ 无页概念 → `NULL` | ✅ 精确（ATX `#`–`######` 栈式归并） | 语法即结构 |
| `.docx` | ❌ 无固定分页 → `NULL` | ✅ 精确（`paragraph.style.name` 命中 `Heading N` / `标题 N`） | 样式即结构 |
| `.txt` | ❌ → `NULL` | ❌ → `NULL` | 无结构 |

> 「留空」是**如实反映可得性**，不是缺陷。报告与 API 需明确 `source_page` 对
> 非 PDF 恒为 `null`、`heading_path` 对 PDF 恒为 `null`。

### 2.3 数据结构与接口（保持向后兼容）

```python
@dataclass(frozen=True)
class TextSegment:
    text: str
    page: Optional[int] = None          # PDF 专用
    heading_path: Optional[str] = None  # md / docx 专用，形如 "3 原理 > 3.2 注意力"

@dataclass(frozen=True)
class TextChunk:
    text: str
    index: int
    page: Optional[int]
    heading_path: Optional[str]
```

| 接口 | 变更 | 兼容性 |
|---|---|---|
| `DocumentParser.parse_segments(file_path, file_type) -> List[TextSegment]` | **新增** | — |
| `DocumentParser.parse(...) -> str` | 改为 `"\n".join(s.text for s in parse_segments(...))` 的薄封装 | **保持原契约**，既有调用方零改动 |
| `TextSplitter.split(text) -> List[str]` | **保持不变**（评测语料与既有单测依赖它） | 不变 |
| `TextSplitter.split_segments(segments) -> List[TextChunk]` | **新增**，段内切分 + 元数据随段下发 | — |

> 为什么不改 `split()` 的返回类型：它是评测链路（`index_rag_eval_corpus.py`）与
> 大量单测的既有契约，改签名属破坏性变更，收益仅为「少一个方法」。

### 2.4 决策点 3：元数据存哪里

**结论：只落 MySQL 列（`heading_path` 新增、`source_page` 启用），Qdrant payload 不加字段。**

论证（沿用本项目既有约定「新增字段前先问：它是否驱动代码分支 / 是否被读取」）：

1. **读取路径已经回表**：`search()` 必须 JOIN `knowledge_chunks` 取 `content`，页码/标题
   与 `content` 同源同行——**加 payload 不会省掉任何一次回表**。
2. **payload 有索引成本与一致性成本**：Qdrant 侧多一份副本就多一处要同步的状态，
   而当前没有任何检索过滤（filter）需要按页/标题下推。
3. 一旦将来要做「限定某章节检索」这类**过滤下推**，那时再加 payload 才有依据——
   届时重建索引本身就是唯一必需的代价，迟加不亏。

`search()` 结果项新增两个字段（结构变更，向后兼容）：

```python
item["source_page"]  = chunk.source_page    # 非 PDF 为 None
item["heading_path"] = chunk.heading_path   # PDF 为 None
```

### 2.5 影响面清单

| 文件 | 改动 |
|---|---|
| `app/utils/document.py` | 新增 `TextSegment` / `TextChunk`；`parse_segments()`；`parse()` 改薄封装；`split_segments()`（段内切分，逐段复用现有 `_split_recursive`） |
| `app/models/knowledge_chunk.py` | 新增 `heading_path = Column(String(512), nullable=True)` |
| `app/services/knowledge_processor.py` | 改用 `parse_segments` + `split_segments`；`source_page` / `heading_path` 真实落库；payload 保持四键不变 |
| `app/services/knowledge.py` | `search()` 结果项补 `source_page` / `heading_path` |
| `app/repositories/*`（chunk） | 无需改动（整行对象已足够） |
| `tests/test_document_segments.py`（新增） | 分段与段内切分、页码/标题归属、PDF 标题留空、`parse()` 契约不变 |
| `tests/test_knowledge_search_hybrid.py` | 补结果字段断言 |

### 2.6 验收标准

1. 三段式测试：PDF 块的 `page` 唯一且落在 `[1, 总页数]`；MD 块的 `heading_path` 与实际标题栈一致；同块 `page` 不跨页。
2. `DocumentParser.parse()` 对同一文件的返回值与改造前**逐字符相等**（回归断言）。
3. `search()` 返回项含 `source_page` / `heading_path`（`None` 时也显式出现）。

---

## 3. 5.6 迁移设计

### 3.1 一次迁移、两列

| 表 | 列 | 用途 |
|---|---|---|
| `knowledge_chunks` | `heading_path VARCHAR(512) NULL` | D12 标题路径 |
| `knowledge_bases` | `active_collection VARCHAR(80) NULL` | **灰度/回滚指针**（见 §4.3） |

```python
revision = "<新 id>"
down_revision = "h2i3j4k5l6m7"   # 当前单一 head

def _has_column(table, column) -> bool: ...   # 沿用 h2i3j4k5l6m7 的幂等守卫写法

def upgrade():
    if not _has_column("knowledge_chunks", "heading_path"):
        op.add_column("knowledge_chunks", sa.Column("heading_path", sa.String(512), nullable=True))
    if not _has_column("knowledge_bases", "active_collection"):
        op.add_column("knowledge_bases", sa.Column("active_collection", sa.String(80), nullable=True))
```

### 3.2 交付标准（**不是迁移文件，而是已生效的库**）

本项目已有过一次「只交迁移文件、未执行」导致启动即 `Unknown column` 的教训，故本次把
执行与验证写成硬性三步，缺一不算完成：

```bash
# 1) 结构落库
docker exec -w /app ai-studio-backend alembic upgrade head

# 2) 版本对齐：current 必须等于 heads
docker exec -w /app ai-studio-backend sh -c 'alembic current; alembic heads'

# 3) 直连库验证新列真实存在
docker exec -i ai-studio-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ai_studio -e "
SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA=\"ai_studio\"
  AND ((TABLE_NAME=\"knowledge_chunks\" AND COLUMN_NAME=\"heading_path\")
    OR (TABLE_NAME=\"knowledge_bases\"  AND COLUMN_NAME=\"active_collection\"));"'
```

> MySQL DDL 非事务，失败可能**已部分生效**；`_has_column` 守卫使迁移可安全重跑。

---

## 4. 5.8 重建设计

### 4.1 前置校验（已实测，结论：通过）

| 检查 | 结果 |
|---|---|
| 存活文档原件在位率 | **1/1 ✓**（`Happy-LLM-0727.pdf`，md5 已记录） |
| 免重嵌入的替代路径 | **不存在**（分块已变，旧向量不可复用） |
| 备份 | 重建前导出 `knowledge_chunks`（301+905 行）与 `knowledge_documents` 为 SQL dump |

### 4.2 缺口修复：`index_rag_eval_corpus.py` 需支持一次写成混合布局

当前该脚本用 `get_or_create_collection(slug, dim)` 建**匿名稠密**集合，要再跑一次
`backfill_hybrid_collection.py` 才能变混合布局——**这正是「建两次」**。

| # | 改动 | 说明 |
|---|---|---|
| a | 新增 `--hybrid` | 用 `create_hybrid_collection()` 建「命名稠密 + 命名稀疏」，写入时用 `hybrid_point_vector(dense, sparse_indices, sparse_values)` |
| b | 新增 `--out-dir` | **与 `--data-dir` 分离**：新配置的 `chunks.jsonl` / `index_manifest.json` / `cut_report.json` 写到独立目录，**不覆盖 1024 基线的清单**（旧基线必须保持可复现） |
| c | 支持 `--idf` | 透传给稀疏编码器（与回填脚本对齐，便于复现 `_hybrid_idf` 结论） |

### 4.3 双写 + 灰度 + 回滚

**关键手法：给 `vector_id` 加「分块代次」后缀。**

```python
CHUNK_EPOCH = f"{config.chunk_size}-{config.chunk_overlap}"   # "448-64"
vector_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc.id}_{index}@{CHUNK_EPOCH}"))
```

这一步同时解决三个问题：

1. **唯一约束冲突（真陷阱）**：`knowledge_chunks.vector_id` 上有**唯一索引**，而
   `deleted_at` 软删**不释放**该值——实测 905 行软删记录仍占着 905 个 `vector_id`。
   重建沿用同一 `doc.id` 与序号时，新旧 id 完全相同 → 插入必然 `IntegrityError`。
   加代次后缀后新旧 id 天然不同，**不会撞**。
2. **新旧共存安全**：`search()` 用「Qdrant 命中的 `vector_id`」回表，所以只要查询的是
   新集合，就**只会命中新行**；旧行留在库里不干扰检索，天然支持双写期间并行验证。
3. **可回滚且幂等**：同一配置重跑得到同一批 id（幂等）；回滚只需把指针指回旧集合。

**灰度/回滚指针**：`knowledge_bases.active_collection`

| 状态 | `active_collection` | 读写去向 |
|---|---|---|
| 未重建（默认） | `NULL` | 现名 `kb_{kb_id}`（行为与今天完全一致） |
| 已切流 | `kb_{kb_id}_v2` | 该集合 |
| **回滚** | 置回 `NULL` | 立刻退回旧集合（旧集合与旧行都在） |

解析处集中在 `collection_name_for()` 一处（写入与检索共用），并把 `kb.active_collection`
作为覆盖值传入——**只有一个真值来源，不存在两处漂移**。

### 4.4 评测语料重建（一次写成混合布局）

```bash
# 448/64 + 命名稠密/稀疏，写入新集合与独立产物目录（保留 1024/0 旧基线）
docker exec -w /app -e PYTHONPATH=/app ai-studio-backend \
  python scripts/index_rag_eval_corpus.py \
    --data-dir /app/data/rag_eval \
    --out-dir  /app/data/rag_eval/v3_448_64 \
    --kb-slug  rageval_t2r_v3 \
    --chunk-size 448 --chunk-overlap 64 \
    --hybrid --recreate
```

产物：`kb_rageval_t2r_v3`（6 万级点）、`v3_448_64/chunks.jsonl`、`v3_448_64/index_manifest.json`、
`v3_448_64/cut_report.json`。旧集合 `kb_rageval_t2r{,_hybrid,_hybrid_idf}` **全部保留**。

### 4.5 业务库重建（新增脚本 `scripts/rebuild_knowledge_vectors.py`）

对齐 `backfill_hybrid_collection.py` 的**安全设计风格**（默认只读、目标存在则拒绝、可抽样）：

| 参数 | 作用 |
|---|---|
| `--kb-id` | 待重建知识库（必填） |
| `--target-collection` | 目标集合名，默认 `kb_{kb_id}_v2` |
| `--execute` | 缺省只打印计划（文档数 / 预计块数 / 预计耗时 / 目标名），**不写任何数据** |
| `--recreate` | 目标已存在时先删除（防半成品续写） |
| `--limit-docs` | 只处理前 N 篇（链路验证） |
| `--cutover` | 校验通过后置 `active_collection` + 软删旧分块行 + 更新计数 |
| `--rollback` | `active_collection` 置 `NULL`（旧集合与旧行均在，立即生效） |

单篇流程：

```
读文件（校验落盘件在位）→ parse_segments → split_segments（448/64）
→ 批量 embed → upsert 到目标集合（命名稠密 + 命名稀疏）
→ 插入新分块行（代次化 vector_id + page + heading_path）→ 更新 doc.chunk_count
```

`--cutover` 阶段：置 `kb.active_collection` → 更新 `kb.chunk_count` = 新存活分块数 →
软删旧代次分块行。**旧 Qdrant 集合保留一个回滚窗口**后再显式删除。

### 4.6 验收标准

| # | 验收项 | 判定 |
|---|---|---|
| 1 | 重新分块后端到端检索可用 | 对生产 PDF 跑 `search()`，返回项含 `content` / `score` / **`source_page`** |
| 2 | 计数一致 | `kb.chunk_count` = `knowledge_chunks` 存活行数 = Qdrant 目标集合点数 = **634**（实测预期） |
| 3 | 截断归零 | 新集合全部分块 `token ≤ 512`（复核命令见 §1.1 脚本） |
| 4 | 混合生效 | 目标集合 `layout == "hybrid"`；开 `retrieval_hybrid_enabled` 后 `search()` 走双路融合 |
| 5 | 回滚可用 | `--rollback` 后 `search()` 立刻返回旧集合结果 |
| 6 | 旧基线可复现 | 用保留的 `kb_rageval_t2r` + 原 `baseline.json` 重跑仍得到同一组指标 |
| 7 | 端到端对照 | 448/64 下 dense 与 hybrid(α=0.7) 各出一份指标，与 1024 基线**分段对比**（分块变了，绝对值得分开陈述） |

---

## 5. 执行顺序、依赖与批次

| 序 | 任务 | 依赖 | 是否阻塞后续 | 预估 |
|---|---|---|---|---|
| 1 | §3 迁移（两列）执行 + 三项验证 | — | 阻塞 2/3/4 | 分钟级 |
| 2 | §2 `parse_segments` / `split_segments` + 单测 | 1 | 阻塞 3 | 编码为主 |
| 3 | §4.2 `index_rag_eval_corpus.py --hybrid/--out-dir` + 单测 | — | 阻塞 5 | 编码为主 |
| 4 | §2 `knowledge_processor` 接新接口 + `search()` 补字段 + 单测 | 1,2 | 阻塞 6 | 编码为主 |
| 5 | §4.4 评测语料重建（**长任务，10.3 h**） | 3 | 阻塞 7 | **≈10.3 h** |
| 6 | §4.5 业务库重建 + cutover | 4 | 阻塞 8 | **≈8 min** |
| 7 | §4.4 评测对照（dense + hybrid 两组） | 5 | — | 分钟级 |
| 8 | 回归测试（容器全量）+ 代码审查 | 4,6 | — | 分钟级 |
| 9 | 文档回写（实施报告 §3.6 / PLAN.md / EVALUATION-REPORT.md） | 全部 | — | 分钟级 |

> 1–4 是**纯代码 + 迁移**，可立即执行且不依赖长任务；5 是唯一的算力瓶颈。
> 建议 5 与 6/8 并行：评测重建在后台跑，业务库重建（8 分钟）先完成并验收。

---

## 6. 成本预算

| 项 | 量 | 吞吐 | 耗时 |
|---|---|---|---|
| 评测语料嵌入 | 52,068 块 | 1.4 块/秒 | **≈10.3 h**（本机下限，无法并行加速） |
| 评测语料解析 + 分块 + 写入 | 20,000 段 | — | 分钟级 |
| 生产库嵌入 | 634 块 | 1.4 块/秒 | **≈7.5 min** |
| 生产库解析 | 1 篇 / 19.76 MB | 6.3 s | 秒级 |
| Qdrant 新增存储 | 评测 ≈88 MB 稠密 + ≈83 MB 稀疏；生产 <10 MB | — | 可忽略 |

---

## 7. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| `vector_id` 唯一索引冲突 | 重建插入直接失败 | **代次化 id**（§4.3）；重建前先跑 `--limit-docs 1` 验证 |
| 迁移只落文件未执行 | 启动报 `Unknown column` | §3.2 强制三步验证 |
| 10.3 h 长任务被中断 | 算力作废 | 评测重建按 `UPSERT_BATCH` 批次落盘，中断后**重跑幂等**（同段落同序号 → 同 id）；必要时缩 `--limit-passages` 做分段验证 |
| 分块参数变更使绝对指标不可直接对比 | 结论误读 | 报告**分开陈述**「旧分块旧指标」与「新分块新指标」，增益只在同一分块口径内比较 |
| 新块数 +81%（28,771 → 52,068） | 存储与延迟上升 | 实测混合检索延迟 p50 仅 +2~3 ms；存储增量已列于 §6 |
| 旧集合误删 | 失去回滚与基线 | 回滚窗口内**不删**旧集合；删除须显式单独操作 |
| 生产重建期间用户上传 | 新文档按新参数入库，与重建互不干扰（同一 `collection_name_for` 解析） | 若已 cutover，新上传直接进新集合；若未 cutover，先入旧集合、需在 cutover 前重跑一次 |
| 磁盘占用（本机可用约 9.6 GiB） | 落盘失败 | 评测新增约 170 MB、生产 <10 MB，余量充足 |

---

## 8. 待你决策

| # | 决策点 | 选项 | 建议 |
|---|---|---|---|
| D-1 | 元数据携带方式 | **A1 段内切分（严格页码归属）** / A2 跨段合并（起始页归属） | **A1**（可精确断言） |
| D-2 | 灰度指针载体 | **`knowledge_bases.active_collection` 列** / 配置文件映射 | **列**（唯一真值来源，可回滚） |
| D-3 | 评测新索引命名 | **`rageval_t2r_v3` + `data/rag_eval/v3_448_64/`（保留旧基线）** / 复用 `rageval_t2r` 覆盖 | **新建**（保住旧基线可复现） |
| D-4 | 是否顺带切换 embedding 模型（PLAN Q3） | 维持 `bge-base-zh-v1.5`（768 维） / 切 `bge-m3`（1024 维） | **维持**：切换会把「分块修复」与「模型切换」两个变量混在一起，无法归因；且需重跑全部基线 |
| D-5 | 评测重建何时排队跑 | 现在后台跑（10.3 h） / 先完成 1–4 与业务库重建再跑 | 先做 1–4（代码/迁移，不受算力约束），算力窗口再确认 |

**确认后按 §5 的 1 → 9 顺序执行**，每步完成后运行单测并回写文档；第 8 步执行代码审查三问。
