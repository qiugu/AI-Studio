# 检索质量评测报告（批次 2）

- 文档版本：**v1.0**
- 日期：2026-09-12
- 对应计划：[PLAN.md](./PLAN.md) Phase 2 / Phase 3 / Phase 4
- 交付批次：**批次 2**
- 相关文档：[RERANKER-DESIGN.md](./RERANKER-DESIGN.md)、[batch1-delivery.md](./batch1-delivery.md)

---

## 1. 摘要

1. **评测能力已端到端可用**：公开中文基准 `mteb/T2Retrieval` → 采样数据集成型 →
   真实分块与向量化入库 Qdrant → 宽召回 →（可选）CrossEncoder 精排 → 指标与对照报告，
   全链路跑通，全部产物可复现（`seed=42`，清单落盘）。
2. **纯稠密基线**（100 查询、20,000 段落语料、段落粒度）：`Recall@5 = 0.8667`、
   `Recall@10 = 0.8900`、`MRR@10 = 0.8423`、`nDCG@10 = 0.8381`，
   召回延迟 p50 = 61.4 ms / p95 = 84.0 ms。
3. **排序损失确认为主要瓶颈**：`candidate_k=100` 的段落级召回上限为 `0.9600`，
   而基线 `Recall@10` 为 `0.8900`——**7.0pp 的差距属于纯排序损失**，
   是精排的理论收益空间。
4. **精排在本机硬件上不具备交互式可用性**（本批次最重要的负面结论）：
   实测 MPS 2.69 对/秒、CPU 1.59 对/秒，`candidate_k=20` 即需 7~13 秒/查询，
   `candidate_k=100` 需 37~63 秒/查询。`reranker_enabled` 保持默认 `False` 是正确决策。
5. **评测过程暴露 3 类环境/工程缺陷**并已修复：配置文件空值键内联注释导致检索链路
   整体失效（整轮 100/100 失败）、`HTTP_PROXY` 拦截 localhost 请求导致 502、
   HuggingFace 联网重试阻塞。均已固化规避方式与回归测试。

**批次结论**：Phase 2 / Phase 3 完成；Phase 4 的质量对照已完成，但**不建议在本期开启
精排**——延迟不可接受，且真正的损失大头需要 Phase 5 的混合检索来修（见 §8）。

---

## 2. 评测口径与可复现性

### 2.1 数据集

| 项 | 值 |
|----|----|
| 来源 | `mteb/T2Retrieval`（中文长文检索，非 gated） |
| 修订 | `921dd3af6e78d1ae7ee0368aa8d7eaee02c8f08e` |
| 采样 | reservoir，`seed=42`，`M=20000` 段落（候选池 118,256，采样比 **16.9%**） |
| 查询 | 100 条（从 588 条「相关段落全部落在采样语料内」的查询中取前 100） |
| 相关标注 | 二值（`rel ∈ {0,1}`）；共 123 个相关段落，每查询 1~3 个（均值 1.23） |
| 查询分型 | `rel1` 80 条 / `rel2` 17 条 / `rel3plus` 3 条 |

**采样偏差声明（必须随结论一起引用）**：语料是基准的子集，干扰项同比例减少，
因此**绝对 Recall 会高于全量场景**。本报告的结论仅用于比较不同检索配置之间的
**相对增益**，不可直接外推为线上绝对指标。

### 2.2 索引

| 项 | 值 |
|----|----|
| collection | `kb_rageval_t2r` |
| Embedding | `BAAI/bge-base-zh-v1.5`（768 维，本地，MPS） |
| 分块 | `TextSplitter(chunk_size=1024, chunk_overlap=128)` |
| 规模 | 20,000 段落 → **28,771 分块**（实测 Qdrant 点数 28,771，与 `chunks.jsonl` 一致） |
| 切断情况 | 4,195 段落被切分；相关段落中 24/123（19.5%）被切分，影响 23/100 查询 |

**关于分块切断的口径决策**：基准的标准答案是**段落**，索引单元是**分块**。若在分块
粒度算 Recall，指标会随 `chunk_size` 变化——而 Phase 5 正要调整该参数，那样两次结果
就无法比较。因此评测在检索链路最外层把命中分块**映射回段落并去重**（`chunks.jsonl`
固化映射关系），并在**段落粒度**打分。切断因此不会人为压低 Recall 上限，
`cut_report.json` 的用途转为**披露信号稀释程度**。

> 相关缺陷 **D11**（已知，未修）：`TextSplitter._merge_splits` 未把 `chunk_overlap`
> 纳入长度计算，声明的 128 字符重叠**实际为 0**。这会让跨块边界的答案被一分为二，
> 直接压低 Recall 上限。纳入 Phase 5 修复（`test_text_splitter.py` 中以 `xfail` 标记）。

### 2.3 指标口径

| 指标 | 定义 | 说明 |
|------|------|------|
| `Recall@k` | `|R ∩ T_k| / |R|`，分母是**完整相关集** | 主指标；衡量召回上限 |
| `Precision@k` | `|R ∩ T_k| / k`（分母为 `min(k, |返回条数|)`） | 本语料每查询仅 1~3 个相关段落，该值天然偏低，仅作参考 |
| `MRR@k` | `rr@k` 的单查询宏观平均 | 位置敏感 |
| `nDCG@k` | 二值增益 | 声明：**nDCG 使用二值增益**，非分级增益 |
| `MAP@k` | 平均精度 | |
| `candidate_recall` | 宽召回候选集内的 Recall | **与 `Recall@k` 之差即纯排序损失** |
| `Latency p50/p95` | 召回 / 精排 / 端到端分段计时 | 性能基线 |

所有指标均为**单查询宏观平均**（每查询等权）。

### 2.4 可复现性清单

- `data/rag_eval/manifest.json`：采样来源、修订号、种子、采样比、查询筛选统计
- `data/rag_eval/index_manifest.json`：collection、模型、维度、分块参数、规模
- `data/rag_eval/chunks.jsonl`：分块 → 段落映射（构建期固化，避免运行时二次推导）
- `data/rag_eval/cut_report.json`：切断披露
- `data/rag_eval/reports/*.json`：逐查询指标明细（含 `retrieved_ids` 与 `error`）

---

## 3. 基线结果（Phase 4.1，纯稠密检索）

命令：

```bash
cd backend
python scripts/rag_eval.py --retriever qdrant --index-dir data/rag_eval \
    --name baseline --out-dir data/rag_eval/reports
```

### 3.1 总体指标

| 指标 | @1 | @3 | @5 | @10 |
|------|------|------|------|------|
| **RECALL** | 0.7100 | 0.8167 | **0.8667** | **0.8900** |
| HIT | 0.8100 | 0.8500 | 0.8900 | 0.9100 |
| PRECISION | 0.8100 | 0.3333 | 0.2120 | 0.1090 |
| MRR | 0.8100 | 0.8300 | 0.8390 | **0.8423** |
| MAP | 0.7100 | 0.7933 | 0.8068 | 0.8116 |
| nDCG | 0.8100 | 0.8081 | 0.8294 | **0.8381** |

### 3.2 分查询类型（`k=5`）

| 查询类型 | 查询数 | recall@5 | mrr@5 | ndcg@5 |
|------|------|------|------|------|
| `rel1` | 80 | 0.8750 | 0.8113 | 0.8270 |
| `rel2` | 17 | 0.8235 | 0.9412 | 0.8247 |
| `rel3plus` | 3 | 0.8889 | 1.0000 | 0.9218 |

### 3.3 延迟

| 阶段 | p50 | p95 | mean |
|------|-----|-----|------|
| retrieve | 61.4 ms | 84.0 ms | 146.1 ms |
| total | 61.4 ms | 84.0 ms | 146.1 ms |

### 3.4 失败结构（决定该修召回还是该上精排）

| 类别 | 查询数 | 类型分布 |
|------|--------|----------|
| 完全漏检（`recall@10 = 0`） | **9** | `rel1` 8、`rel2` 1 |
| 部分漏检（`0 < recall@10 < 1`） | **4** | 全部为 `rel2` |
| 全命中 | 87 | — |

共 13 条查询存在漏检，平均每条查询漏掉 0.140 个相关段落。

结合 §5 的召回上限曲线可把损失拆开：

- **排名损失（精排可修）**：`0.9600 − 0.8900 = 7.0pp`
- **召回损失（精排不可修）**：`1 − 0.9600 = 4.0pp`，需 Phase 5 混合检索

**这说明精排不是当前的主要抓手**：它能触及的空间是 7.0pp，而剩下 4.0pp 只有
改善召回（稀疏/混合检索）才能拿回。两者应当是先后关系而非替代关系。

---

## 4. 精排对照结果（Phase 4.2）

<!-- RERANKED_SECTION_PLACEHOLDER -->

---

## 5. 调参依据：`candidate_k` 召回上限曲线（Phase 4.3）

精排**只能重排已经召回的候选**，因此 `candidate_k` 直接决定质量天花板。实测
（`scripts/rag_eval_candidate_curve.py`，与正式评测同口径）：

| candidate_k | 段落级 Recall 上限 | 相对 `k=10` 增益 |
|-------------|--------------------|-------------------|
| 10 | 0.8900 | +0.0000 |
| 20 | 0.8950 | +0.0050 |
| 50 | 0.9050 | +0.0150 |
| **100** | **0.9600** | **+0.0700** |
| 200 | 0.9600 | +0.0700 |

**结论**：

1. 曲线在 **`k=100` 进入平台**（`k=200` 与 `k=100` 完全相同），因此 `k=100` 是
   召回上限的性价比拐点。
2. **配置默认值 `reranker_candidate_k=20` 在本语料上几乎没有空间**：上限 0.8950
   仅比纯稠密 `recall@10`（0.8900）高 0.5pp。按默认值开启精排，几乎不可能观测到收益
   ——这不是「精排无效」，而是候选集没给它留出余量。
3. 因此本批次的精排对照选择 `candidate_k=100`。生产上若决定启用精排，也应先把
   该值提到 100，并接受相应延迟（见 §6）。

---

## 6. 精排延迟与部署可行性（Phase 3.4）

测量条件：`bge-reranker-v2-m3`、`max_length=512`、真实分块文本（约 1024 字符，
中文接近 1 字 ≈ 1 token，故多数输入被截断到 512 token）、权重本地缓存、64 对样本
（另以 128 对样本复核 batch 扫描）。本机为 Apple Silicon、无 CUDA。

| 设备 | 模型加载 | 精排吞吐 | `candidate_k=20` | `candidate_k=100` |
|------|----------|----------|------------------|-------------------|
| CPU | 2.1 s | 1.59 对/秒 | 约 12.6 s/查询 | 约 62.9 s/查询 |
| **MPS** | 1.9 s | **2.69 对/秒** | 约 7.4 s/查询 | 约 37.2 s/查询 |

`batch_size` 扫描（MPS，128 对样本）：

| batch_size | 吞吐 | 结论 |
|------------|------|------|
| **32** | **2.76 对/秒** | 既有默认值，本机最优 |
| 64 | 2.34 对/秒 | 反而更慢 |
| 128 | 1.49 对/秒 | 显著更慢 |

**为什么更大的 batch 更慢**：在本机高内存压力下（Docker VM 与浏览器占用，
系统压缩器约 5.8 GB），更大的 batch 抬高激活内存峰值并加剧换页，收益被换页开销
吃掉。既有默认 `reranker_batch_size=32` 无需调整。

**部署结论**：精排的耗时是**刚性**的——568M 参数 CrossEncoder 在 `max_length=512`
下单批 32 对约需 1.9e13 FLOPs，本机 CPU/MPS 只能提供个位数 TFLOPS 有效算力。
因此：

1. `reranker_enabled` 默认 `False` 是正确决策，**不应在同步请求路径上默认开启**；
2. 如需启用，应限定高价值场景（显式「深度检索」）或异步/离线批处理；
3. 需要交互式精排时必须引入 CUDA，或改用更小的重排模型并下调 `max_length`。

---

## 7. 本批次发现的环境与工程缺陷

评测体系的价值之一是**把平时看不见的配置缺陷暴露成可量化的失败**。本批次共暴露 3 类：

### 7.1 配置文件空值键内联注释（新登记：D13，已修复）

`backend/.env` 曾写作：

```env
QDRANT_API_KEY=              # 本地部署可留空；云端部署时填写
```

`python-dotenv` 对**空值**后的 `#` **不做注释剥离**，注释整段成为配置值：
`qdrant_api_key = "# 本地部署可留空；云端部署时填写"`。该值被 `QdrantClient` 当作
HTTP header 传入，`httpx` 在构造请求头时按 ASCII 编码失败：

```
UnicodeEncodeError: 'ascii' codec can't encode characters in position 2-16
```

**后果**：整轮评测 100 条查询全部失败，CLI 输出「查询数 0（失败 100）」，所有指标
为 0.0000——从报告上看像是「检索效果极差」，而不是「配置读错」。

**为什么隐蔽**：同一文件里 `DATABASE_SOCKET=/tmp/mysql.sock   # 注释` 是**安全**的
（`#` 前有非空值，dotenv 正常剥离）。该缺陷只在**空值键**上触发。

**修复**：
1. 把注释单独成行，`QDRANT_API_KEY=` 保持真正为空；同步修复 `EMBEDDING_API_BASE`
   （同类潜在缺陷，值为 `# 可选，自定义 / 兼容接口的 Base URL`）与 `.env.example`；
2. 新增回归测试 `backend/tests/test_env_file_hygiene.py`：断言解析后的值不得以 `#`
   开头，且模板值必须为 ASCII。

### 7.2 `HTTP_PROXY` 拦截 localhost 请求（环境约束，已固化规避方式）

本机环境存在 `HTTP_PROXY=http://127.0.0.1:51838`（工具链注入）。`httpx` 默认
`trust_env=True`，会把发给 `localhost:6333` 的请求交给该代理，代理再向上游连接失败，
返回 **502 Bad Gateway**：

```
qdrant_client.http.exceptions.UnexpectedResponse: Unexpected Response: 502 (Bad Gateway)
Raw response content: b'upstream connect failed: Connection refused (os error 61)\n'
```

**规避**：所有访问本机服务的评测命令显式设置

```bash
NO_PROXY=localhost,127.0.0.1,::1  no_proxy=localhost,127.0.0.1,::1
```

诊断时的等价手段是 `curl --noproxy '*'`。

### 7.3 依赖与运行时环境

| 现象 | 根因 | 处置 |
|------|------|------|
| 模型加载阻塞约 7 分钟 | `huggingface_hub` 对本机网络不可达的 `huggingface.co` 发 HEAD 请求，10 s 超时 × 5 次重试 × 多个文件 | 权重已缓存，评测统一加 `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`；`HF_HOME` 指向工作区外置缓存 |
| 评测中途 Qdrant 不可达 | Docker Compose 栈整体停止（容器不存在，**数据卷完好**） | `docker compose up -d` 恢复；恢复后校验 Qdrant `kb_rageval_t2r` = 28,771 点、MySQL 知识库 2 个，**数据无损** |
| `docker` 命令找不到 | 当前 shell PATH 不含 `/usr/local/bin` | 使用绝对路径 `/usr/local/bin/docker` |

---

## 8. 结论与建议

### 8.1 对检索链路的判断

| 判断 | 证据 | 建议 |
|------|------|------|
| 稠密召回本身不差 | `Recall@10 = 0.8900`，87/100 查询全命中 | 维持现有召回链路 |
| 主要瓶颈是排序与召回边界 | 7.0pp 排序损失 + 4.0pp 召回损失 | 先修分块与召回（Phase 5），再评估精排 |
| 精排延迟不可接受 | 7.4~62.9 s/查询（视 `candidate_k`） | **本期不开启** `reranker_enabled` |
| `candidate_k` 默认值偏小 | `k=20` 上限仅 0.8950，`k=100` 为 0.9600 | 若启用精排，先提到 100 |
| 分块重叠未生效 | D11（`chunk_overlap` 实际为 0） | Phase 5 必修，直接影响 Recall 上限 |

### 8.2 建议的后续优先级

1. **Phase 5.5 修 D11 分块重叠**——成本最低、直接抬升 Recall 上限。
2. **Phase 5 混合检索（稀疏 + 稠密 + RRF）**——回收那 4.0pp 的召回损失，且
   **没有精排的延迟代价**。
3. **精排暂缓**：作为可选能力保留实现与开关，待 CUDA 部署或更小模型可用时再评估；
   若必须启用，限定为异步/离线批量场景，`candidate_k=100`。
4. 修复后按同一口径重跑本报告，与 §3/§4 逐项对比（回归门禁：`Recall@5` 下降 ≤ 1pp）。

---

## 9. 附录：复现命令

```bash
cd backend

# 1) 采样数据集（需联网，走 hf-mirror；仅在需要重建数据集时执行）
HF_ENDPOINT=https://hf-mirror.com python scripts/prepare_rag_eval_dataset.py

# 2) 真实链路入库 + 分块切断检测（约 55 分钟，MPS）
HF_HOME=<外置缓存目录> python scripts/index_rag_eval_corpus.py \
    --kb-slug rageval_t2r --device mps --recreate

# 3) 基线（纯稠密）
NO_PROXY=localhost,127.0.0.1,::1 python scripts/rag_eval.py \
    --retriever qdrant --index-dir data/rag_eval --name baseline

# 4) candidate_k 召回上限曲线
NO_PROXY=localhost,127.0.0.1,::1 python scripts/rag_eval_candidate_curve.py

# 5) 精排对照（本机约 60 分钟）
NO_PROXY=localhost,127.0.0.1,::1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python scripts/rag_eval.py --retriever qdrant --index-dir data/rag_eval \
    --rerank --candidate-k 100 --rerank-device mps \
    --name reranked --baseline data/rag_eval/reports/baseline.json
```

**前置条件**：Docker 栈（MySQL / Qdrant / Redis）已启动；
`backend/.env` 中空值键不得带行内注释（见 §7.1）。

---

## 10. 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-09-12 | v1.0 | 批次 2 交付：Phase 2 采样入库、Phase 3 精排接入、Phase 4 对照实测 |
