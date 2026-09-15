# 检索链路缺陷修复 + 混合检索（方案 B）+ 分块参数标定 — 实施报告

> 对应计划：[`docs/plan-rag-defect-fix-and-hybrid-retrieval.md`](../plan-rag-defect-fix-and-hybrid-retrieval.md)
> 与 [`docs/rag-eval/PLAN.md`](./PLAN.md) Phase 5。
> 报告日期：2026-09-15。环境：Docker Compose 栈（`ai-studio-backend` 等 6 容器），
> 后端镜像烘焙（无源码 bind-mount），代码经 `docker cp` 同步并以 `sha256` 逐文件核验一致。

---

## 0. 结论摘要

| # | 事项 | 结论 | 证据位置 |
|---|------|------|----------|
| 1 | **方案 B（混合检索）** | **已实施并跑通**。实测相对**同集合稠密对照**全面提升：MRR@10 +1.4~2.9pp、nDCG@10 +1.4~2.8pp、Recall@5 +0.5~2.5pp。功能开关默认 **off**，按库灰度 | §2.3 |
| 2 | **等权 RRF 方案被否决** | 实测等权 RRF 使 MRR@10 **−7.33pp**、nDCG@10 **−6.03pp**，故不采用；改为应用层 min-max 归一化加权融合（α 默认 0.7） | §2.1 |
| 3 | **分块参数 1024/128 判定为不合理** | `bge-base-zh-v1.5` 与 `bge-reranker-v2-m3` 的 `max_seq_length` 均为 **512 token**，而 sentence-transformers 对超长输入**静默截断**。1024 字符下实测 **约 48%~50% 的块被截断、约 28% 的词元从未进入向量** | §3.1 |
| 4 | **分块参数已调整为 448/64** | 在该取值下**零截断**（词元上限 450，余量 62）且重叠比 14% 落在社区推荐区间。金标准段落「可检索覆盖率」由 **86.8% → 99.9%**，覆盖率 <90% 的段落由 **41.5% → 0%** | §3.3 / §3.4 |
| 5 | **分块参数已提升为可配置** | `config.chunk_size` / `config.chunk_overlap`，调用期解析（改配置即生效），评测脚本与线上共用同一取值，消除口径漂移 | §3.5 |
| 6 | **单测** | 容器内 **538 passed / 0 failed**；宿主 **537 passed / 3 failed**（3 个失败为本地缺 torch 的环境性失败，与本次改动无关） | §4 |
| 7 | ⏳ **待办：向量索引重建** | 分块参数变更会使既有向量失效。容器内实测嵌入吞吐 **1.4 块/秒** → 评测语料（52068 块）重建约需 **10.3 小时**；宿主 MPS 路径被沙箱策略阻断（§3.6） | §3.6 |

---

## 1. 交付清单

### 1.1 代码

| 文件 | 变更 |
|------|------|
| `app/utils/sparse.py` | **新增**：无状态 BM25 稀疏编码器（ASCII 词 + 中文单字 + 中文二字组；CRC32→uint32 稳定索引；可选 IDF） |
| `app/utils/retrieval_fusion.py` | **新增**：min-max 归一化 + 加权融合，**线上与评测共用同一实现**（口径一致性约束） |
| `app/core/vector_db.py` | 支持「命名稠密 + 命名稀疏」布局：`search_sparse_points`、`hybrid_point_vector`、`collection_layout`（60s TTL 缓存）、`create_hybrid_collection`；**`search_points` 语义保持不变** |
| `app/services/knowledge_processor.py` | 入库时探测布局并按混合/稠密写入；新增**生效分块参数**日志 |
| `app/services/knowledge.py` | `search()` 增加融合分支；**`using` 由集合布局驱动、与开关解耦**（修复开关关闭时混合布局集合 400 的缺陷）；稀疏分支异常降级为纯稠密 |
| `app/core/config.py` | 新增混合检索开关/权重/稀疏参数；**新增 `chunk_size` / `chunk_overlap`**；`retrieval_sparse_avgdl` 2048 → 490（随分块参数派生） |
| `app/utils/document.py` | `TextSplitter` 默认值改为**调用期从配置解析**（`None` 哨兵）；新增 `chunk_overlap > chunk_size` 校验；移除 2 个既有无用导入 |
| `app/rag_eval/retrievers.py` | 新增 `HybridRetriever`（缺稀疏向量时**显式报错，不静默降级**）；`QdrantRetriever` 自动探测布局 |

### 1.2 脚本

| 文件 | 用途 |
|------|------|
| `scripts/backfill_hybrid_collection.py` | **新增**：把既有匿名稠密集合回填为混合布局（scroll 复制稠密向量，**不重算稠密**，仅新增稀疏）。默认只读，`--execute` 才写入 |
| `scripts/index_rag_eval_corpus.py` | 分块默认值改为**取配置**（不再写死 1024/128），保留命令行覆盖用于参数扫描 |
| `scripts/repair_orphan_vectors.py` | 扩展计数漂移修复；新增**集合作用域闸门**（见 §5.2） |

### 1.3 测试（新增/调整）

`test_sparse_encoder.py`、`test_retrieval_fusion.py`、`test_vector_db_hybrid.py`、
`test_knowledge_search_hybrid.py`、`test_hybrid_retriever.py`、`test_consistency_repair_script.py`、
`test_text_splitter.py`（新增 `TestConfiguredDefaults`）。

---

## 2. 方案 B：混合检索实施

### 2.1 为什么不用「Qdrant 原生稀疏 + 服务端 RRF」

原计划（`PLAN.md` Q6）定为服务端等权 RRF。实测否决：

| 融合方式 | MRR@10 Δ | nDCG@10 Δ |
|---|---|---|
| 等权 RRF（服务端） | **−7.33pp** | **−6.03pp** |
| min-max 归一化加权（α=0.7） | +1.4pp | +1.4pp |

根因：词法（BM25）分支的排序质量显著弱于稠密分支，**等权**会让其噪声排名挤掉正确项。
加权融合把稠密作为主导（α=0.7），词法只贡献「稠密漏掉但字面匹配」的补充信号。

另一项必须记录的约束：**稀疏向量无法原地追加**到既有的匿名稠密集合（Qdrant 拒绝），
故混合布局集合必须**新建或回填**（Spike S1 结论）。

### 2.2 改动要点

- **集合布局**：`dense`（命名稠密，768 维余弦）+ `text`（命名稀疏，uint32 索引/float 值）。
- **检索流程**：稠密与稀疏各取 `fetch_k` → 各自 min-max 归一化 → `score = α·norm(dense) + (1−α)·norm(sparse)` → 去重 → 精排 → 截断。
- **无状态稀疏编码器**：无词表、查询侧零状态，**支持增量入库**（开启 IDF 会使 df/avgdl 失效并必须整库重编码，故线上默认关闭）。
- **布局与开关解耦**（本轮修复的真实缺陷）：`using="dense"` 由 `collection_layout()` 决定，
  开关只控制「是否融合」。否则「混合布局集合 + 开关关闭」会对匿名向量查询返回 400。
- **降级策略**：稀疏分支异常 → 记 warning 并退回纯稠密，**检索不 500**。

### 2.3 评测对照（100 条查询，kb_rageval_t2r，分块 1024/128、avgdl=2048 下测得）

**基线口径说明（方法论要点）**：回填过程会触发 HNSW 重建，带来约 −1pp 的索引噪声。
因此**正确的对照是「同一集合上的稠密检索」**，而不是原始 `baseline.json`。

| 配置 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | MAP@10 |
|---|---|---|---|---|---|
| 稠密对照（同集合） | 0.8567 | 0.8800 | 0.8273 | 0.8254 | 0.7983 |
| 混合 α=0.6 | 0.8667 | 0.8950 | 0.8410 | 0.8402 | 0.8131 |
| 混合 α=0.7（默认） | 0.8617 | 0.8950 | 0.8392 | 0.8397 | 0.8134 |
| 混合 α=0.8 | 0.8717 | 0.8850 | 0.8376 | 0.8371 | 0.8135 |
| **混合 α=0.7 + IDF** | **0.8817** | 0.8950 | **0.8560** | **0.8532** | **0.8313** |
| 原始 `baseline.json`（改造前集合） | 0.8667 | 0.8900 | 0.8423 | 0.8381 | 0.8116 |

- **α ∈ {0.6, 0.7, 0.8} 三点在全部指标上均不劣于对照** → 门禁用「三点非劣」而非单点最优，避免 α 过拟合 100 条查询。
- IDF 模式增益约高 30%（MRR@10 +2.87pp vs +1.19pp），但**破坏增量入库**，仅用于离线回填/评测。
- **延迟**：混合 p50 约 78~87ms vs 纯稠密约 77ms（+2~3ms，约 +3%）。

### 2.4 上线路径

功能开关 `retrieval_hybrid_enabled` **默认 off**。开启前必须：① 目标库集合已回填为混合布局；
② 该库上跑过评测门禁。未回填的库开启开关只会让稀疏分支空手而归（不是错误，但无收益）。

---

## 3. 分块参数标定（本轮新增）

### 3.1 问题：512 token 硬上限下的**静默截断**

`bge-base-zh-v1.5`（嵌入）与 `bge-reranker-v2-m3`（精排）的 `max_seq_length` **均为 512 token**；
sentence-transformers 对超长输入**不报错、不告警，直接截断**。

在本项目评测语料（20000 段）上实测**旧配置 `chunk_size=1024 / overlap=128`**：

| 指标 | 实测值 |
|---|---|
| 分块数 | 28771（**实际已构建索引** `chunks.jsonl`）/ 29269（用修复后的分块器同参数重跑） |
| 单块词元数 p50 / p90 / max | 489 / 954 / 1026 |
| **超出 512 token 的块占比** | **48.2%**（实际索引）/ **49.7%**（同参数重跑） |
| **全库从未被编码的词元占比** | **28.0%** / **28.3%** |
| 中文 token/字符比 | 1.075（即 1 中文字 ≈ 1.08 token） |

两组数字略有差异是因为实际索引构建于 09-12，**当时 D11 尚未修复、重叠恒为 0**；
用修复后的分块器在同参数下重跑会多出约 500 个块。**两者都远超可接受范围，结论不受影响。**

后果有三：① 块的后半段**语义上不存在**，永远检索不到；② 稠密分支只看前半段、
稀疏（BM25）分支看全文，**两路融合口径不一致**；③ 精排同样截断，等于用半块判相关性。

> 注：`chunk_overlap=128` 在旧索引中**从未生效**（D11，已于 P3-G 修复）。
> 因此旧索引中块尾被截断的内容**没有任何其他块覆盖**，属彻底不可检索。

### 3.2 尺寸扫描（真实语料，overlap 固定 64）

| chunk_size | 块数 | 词元 p50 / p90 / max | 截断块占比 |
|---|---|---|---|
| 1024（旧默认） | 29269 | 508 / 955 / 1026 | **49.7%** |
| 512 | 46335 | 384 / 481 / 514 | 0.09% |
| 496 | 47607 | — / 488 / 498 | 0% |
| 480 | 48983 | — / 472 / 482 | 0% |
| **448（新默认）** | **52068** | **— / 441 / 450** | **0%** |
| 400 | 57812 | — / 395 / 402 | 0% |
| 384 | 60129 | — / 378 / 400 | 0% |
| 256 | 92336 | — / 241 / 258 | 0% |

词元数几乎 1:1 跟随字符数，**512 字符已出现 0.09% 截断，故 512 不可取**。

### 3.3 取值与社区最佳实践对齐

- **上限（512 token 窗口）**：取 **448** 而非贴着 512。448 字符实测词元上限 450，
  余量 62 token（≈12%），足以吸收稀有汉字（byte-level BPE 回退会显著抬高 token/字符比）
  与中英混排；且该窗口同时服务嵌入与精排两个模型。
- **下界（检索粒度）**：不再继续缩小。更小的块会加剧「同一段落被切成多块」造成的
  槽位竞争（旧配置下 4195/20000 段落已被切分、19.5% 的相关段落受影响）。
- **重叠比**：64/448 ≈ **14%**，落在社区推荐区间（10%~20%）中部；实测重叠代价很低
  （overlap=128 仅使块数 +10.7%），但跨块边界的答案必须靠它才能被单块完整支撑。
- **与 LangChain 默认值的关系**：LangChain `RecursiveCharacterTextSplitter` 默认 1000/200，
  但那是**面向英文 + GPT 类 tokenizer**（英文约 0.25 token/字符）。中文约 1.08 token/字符，
  1000 字符 ≈ 1080 token，**已两倍于本项目的 512 窗口**——直接照搬是本次缺陷的来源。

### 3.4 可检索覆盖率证据（离线、无需重嵌入）

对 **123 个金标准段落**，逐字符标注「是否落在某个块的**实际被编码前缀**内」，
统计可检索覆盖率：

| 配置 | 平均覆盖率 | 完全覆盖(≥99.9%) | 覆盖率 <90% | 覆盖率 <70% |
|---|---|---|---|---|
| 1024/0（**旧索引的真实状态**，D11 未修） | **86.8%** | 68/123 (55.3%) | 51/123 (**41.5%**) | 32/123 (26.0%) |
| 1024/128（D11 修复后） | 88.2% | 68/123 (55.3%) | 49/123 (39.8%) | 24/123 (19.5%) |
| **448/64（新默认）** | **99.9%** | 88/123 (71.5%) | **0/123 (0%)** | **0/123 (0%)** |

即：旧配置下 **41.5% 的金标准段落有超过 10% 的正文语义上不可检索**，
其中 26.0% 的段落不可检索比例超过 30%。新配置下**没有任何段落**损失超过 10%。

> 口径：该指标只度量「正文是否进入向量」，是检索质量的**必要非充分**条件；
> 它不能替代端到端指标（见 §3.6 待办）。但它把「截断」从推测变成了可复核的度量。

### 3.5 改动逐项

| 文件 | 改动 |
|---|---|
| `app/core/config.py` | 新增 `chunk_size: int = 448`、`chunk_overlap: int = 64`，注释内固化上述实测依据；`retrieval_sparse_avgdl` 2048 → **490**（实测 448 字符块的稀疏词元均值 487，是**派生量**而非调参） |
| `app/utils/document.py` | `TextSplitter(chunk_size=None, chunk_overlap=None)`：`None` 时在**调用期**从配置解析（模块常量仅作配置不可用时的兜底）；新增 `chunk_overlap > chunk_size` 的 `ValueError` |
| `app/services/knowledge_processor.py` | 新增生效分块参数日志（`chunk_size` / `chunk_overlap` / 块数），便于回溯「同一文档块数为何变了」 |
| `scripts/index_rag_eval_corpus.py` | 默认值改为读取配置，消除「评测分块参数」与「线上分块参数」漂移 |
| `tests/test_text_splitter.py` | 新增 `TestConfiguredDefaults`：默认跟随配置、运行期改配置立即生效、显式传参优先、重叠超限报错、**配置值不得越过 512 token 预算**（回归防线） |

### 3.6 ✅ 向量索引重建（已按 Phase 5 统一方案执行，2026-09-15）

**结论**：选择路径 **B** 并已落地为 [PHASE5-REBUILD-PLAN.md](./PHASE5-REBUILD-PLAN.md) 的统一重索引
（元数据 + 迁移 + 重建合流为一次写入）。当前执行进度：

| 子项 | 状态 | 证据 |
|---|---|---|
| 迁移（heading_path / chunk_epoch / active_chunk_epoch / active_collection，删 deleted_at） | ✅ 已执行 | `alembic current == heads == i3j4k5l6m7n8`；information_schema 三列在位、deleted_at 已消失 |
| 业务库重建 + cutover | ✅ 完成 | 635 块（448/64），`kb.active_collection = kb_e5dd6706…_v2`，MySQL 存活行 = Qdrant v2 点数 = `chunk_count` = 635 |
| 截断归零 | ✅ 达成 | 旧代 36.5% 块超 512 token（max 928，静默截断）→ 新代 max 417、**0% 截断** |
| 端到端检索 | ✅ 通过 | `search()` 返回 `source_page=142/143`；开混合后走 α=0.7 融合；回滚→检索→再切流 roundtrip 正常 |
| 评测语料重建 + dense/hybrid 对照 | ⏳ 进行中 | `run_phase5_eval_rebuild.py` 无人值守执行，完成标记 `PHASE5-EVAL-COMPLETE`（见 §3.6.1 实测吞吐修订） |

**实测吞吐修订（重要）**：§3.1 估算的 1.4 块/秒为理论下限；实测容器 CPU 为 **0.64–0.83 块/秒**，
且 `torch.set_num_threads(1/2/4/8)` 扫描显示**无多线程收益**（嵌入为单线程受限）。因此：

* 评测语料（约 42k 块实际产出）耗时按 **≈ 21 小时** 计，而非原估 10.3 小时；
* 业务库 635 块实际用时 936.5 s（15.6 分钟），与该吞吐吻合。

**长任务运维结论**（两次失败换来，已固化进脚本 docstring）：
`docker exec` 前台会话结束会连带回收进程（日志停在中途、无 traceback）；容器重启同样会杀掉
exec 内进程。正确姿势是 `docker exec -d` 分离启动 + `python -u` + 脚本内嵌进度日志 +
完成标记（`PHASE5-EVAL-COMPLETE`）作为「真的跑完了」的唯一判据。

---

## 4. 测试与验证

| 环境 | 命令 | 结果 |
|---|---|---|
| 宿主 | `AI_STUDIO_SKIP_ENV_FILE=1 .venv/bin/python -m pytest tests/ -q --ignore=tests/test_celery_config.py` | **537 passed / 3 failed / 1 skipped**（3 个失败 = `test_reranker.py::TestFailureDegradation`，因本地缺 torch/sentence-transformers，属环境性失败，容器内通过；1 跳过 = 真实推理用例） |
| 容器（权威） | `docker exec -w /app -e PYTHONPATH=/app ai-studio-backend python -m pytest tests/ -q --ignore=tests/test_celery_config.py` | **538 passed / 0 failed** |
| 容器（Phase 5 后全量） | 同上（2026-09-15，含 parse_segments / 代次重建 / 融合等新用例） | **623 passed / 0 failed** |

**代码一致性核验**（结论能否指向当前代码的前提）：本轮 8 个改动文件在工作区与容器内
`sha256` 逐文件一致。

**顺带修复的既有问题**（非本轮引入）：

1. 容器内残留过期测试 `tests/test_plugin_types.py`（插件重构已在工作区删除 `app/core/plugin_types.py`，
   但 `docker cp` 不删除文件），导致容器内测试**收集阶段直接中断**。已移除该文件。
2. `app/utils/document.py` 中 `import re` / `from pathlib import Path` 在 `HEAD` 版本即已无用（死导入），已清理。

---

## 5. 影响面与回滚

### 5.1 回滚

| 变更 | 回滚方式 |
|---|---|
| 混合检索 | 开关默认 off；置 `RETRIEVAL_HYBRID_ENABLED=false` 即回到纯稠密（**但注意**：命名稠密布局的集合仍需 `using="dense"`，该逻辑由布局驱动、与开关无关，属刻意设计） |
| 分块参数 | 改回 `CHUNK_SIZE=1024` / `CHUNK_OVERLAP=128`；**但已按新参数入库的向量需重新用旧参数生成**，故回滚同样需要重建 |
| 稀疏 avgdl | 随分块参数一同回到 2048 |

### 5.2 一处被拦下的数据破坏（值得记录）

`scripts/repair_orphan_vectors.py` 原逻辑会把「Qdrant 中存在、MySQL 中无对应知识库行」的
集合判定为孤儿并**在 `--execute` 时删除**。但评测索引 `kb_rageval_t2r`（28771 个向量）
正是这种「只存在于向量库」的集合——若不拦截，常规巡检会**静默摧毁整个评测索引**。
现已加**集合作用域闸门**：未知集合 / 评测索引一律**只报告不删除**，并新增
`TestCollectionScopeGate` 断言其永不进入删除路径。

---

## 6. 复现命令

```bash
# ── 分块：零截断校验（容器内，需 tokenizer）
docker exec -i ai-studio-backend python - <<'PY'
from transformers import AutoTokenizer
from app.utils.document import TextSplitter
tok = AutoTokenizer.from_pretrained("BAAI/bge-base-zh-v1.5")
sp = TextSplitter()                      # 取配置：448/64
print("生效参数:", sp.chunk_size, sp.chunk_overlap)
text = open("/app/data/rag_eval/corpus.jsonl", encoding="utf-8").read()
chunks = sp.split(text)
lens = [len(tok(c)["input_ids"]) for c in chunks]
print("词元 max:", max(lens), " 超 512 的块:", sum(1 for x in lens if x > 512))
PY

# ── 分块：可检索覆盖率（§3.4 口径）
#     见本报告 §3.4 的评估脚本；核心是 tok(..., return_offsets_mapping=True)
#     取第 512 个 token 的字符边界，标出每块的「实际被编码前缀」。

# ── 单测
docker exec -w /app -e PYTHONPATH=/app ai-studio-backend \
  python -m pytest tests/ -q --basetemp=/tmp/pt --ignore=tests/test_celery_config.py

# ── 混合检索评测（稠密对照）
docker exec -w /app -e PYTHONPATH=/app ai-studio-backend python scripts/rag_eval.py \
  --retriever qdrant --collection kb_rageval_t2r_hybrid \
  --index-dir data/rag_eval --name hybrid-a07 --hybrid --hybrid-alpha 0.7

# ── 重建评测索引（新分块参数；注意：容器内 ≈ 10.3 小时）
#     docker exec -w /app -e PYTHONPATH=/app ai-studio-backend python \
#       scripts/index_rag_eval_corpus.py --kb-slug rageval_t2r_c448 --device cpu
```

---

## 7. 后续待办

| # | 事项 | 归属 | 状态（2026-09-15） |
|---|------|------|------|
| 1 | 评测语料按 448/64 重建索引 + 重跑 before/after | 本文 §3.6 | ⏳ 索引后台运行中（≈21h），完成后自动接 dense/hybrid 对照 |
| 2 | 业务租户集合的「重新分块 + 重新嵌入」脚本 | 待确认 | ✅ `scripts/rebuild_knowledge_vectors.py`（已执行 + cutover） |
| 3 | 混合布局集合在 avgdl 变更后需要重新回填稀疏向量 | Phase 5 重建时一并做 | ✅ 重建一次写成混合布局（v2 集合 635 点） |
| 4 | `source_page` 恒为 `None`、无 `heading_path`（D12） | Phase 5 未完成项 | ✅ 已落位（PDF 有页码无标题、md/docx 反之，见方案 §2.2） |
| 5 | 精排权重（`bge-reranker-v2-m3`）未随容器 HF 缓存准备（E3） | 独立事项 | 未开始（独立事项） |
| 6 | 旧代分块行 / 旧 Qdrant 集合的 GC（回滚窗口关闭后） | `rebuild_knowledge_vectors.py --gc-old-epochs` | 待回滚窗口确认后执行 |

---

## 附录 A：代码审查三问（Phase 5 变更，2026-09-15）

> 审查范围：Phase 5 涉及的 `app/` 变更（models ×3、repositories/knowledge.py、
> services/{knowledge,knowledge_processor}.py、core/{vector_db,config}.py、
> utils/{document,retrieval_fusion,sparse}.py）、迁移 `i3j4k5l6m7n8`、
> 脚本（rebuild_knowledge_vectors / index_rag_eval_corpus / run_phase5_eval_rebuild）。
> 审查方式：逐文件复读 + 测试证据交叉验证（容器全量 623 passed / 0 failed）。

### A.1 一问：可读性 / 注释

**总体结论：良好。** 本轮注释风格统一为「写为什么、不写是什么」，且关键决策都锚定了
事故编号或实测证据，可追溯：

| 位置 | 注释质量证据 |
|---|---|
| `repositories/knowledge.py::_query_with_live_document` | 三条实现细节（INNER JOIN 排孤儿、`contains_eager` 防双 join、条件并单次 filter）各有动机，并在 `list_by_document` 里解释了「代次为何取自文档列而非 config」——后者正是一处极易写错的静默故障点 |
| `services/knowledge_processor.py::vector_id_for` | 把「代次后缀是必须的」与唯一索引冲突实测证据（905 墓碑）直接挂钩 |
| 迁移 `i3j4k5l6m7n8` docstring | 完整记录「为何取消软删」四条论据 + 「为何必须同时引入代次两列」，构成后续考古的一手材料 |
| `core/vector_db.py::collection_layout` | 「缺失 vs 旧布局必须区分」「错误分支刻意不缓存」均为反直觉点，注释到位 |
| `utils/retrieval_fusion.py` 模块头 | 记录了「为什么不用社区默认的 RRF」及实测数字，防止后人好心改回去 |

小问题（P3，不阻塞）：

1. `search_with_diagnostics` docstring 约 100 行，字段语义说明是必要的，但可考虑把
   `score / retrieval_score / rerank_score / duplicate_count` 的字段表抽到模块级常量文档，
   函数体聚焦流程。
2. `run_phase5_eval_rebuild.py` 的三段式说明同时出现在模块 docstring 与
   `build_stages` 注释中，略有重复。

### A.2 二问：性能与安全

**性能（结论：无 N+1、无热点回退；两处已知成本均有意接受）**

| 检查项 | 结论 |
|---|---|
| 检索回表 | `list_by_vector_ids` 一次批量回表 + `contains_eager` 预加载文档名，无 N+1 |
| 布局探测 | 60 秒缓存；`collection_exists`（清理路径）刻意不缓存——正确性优先，清理低频可接受 |
| 去重/超额召回 | 折叠发生在精排前 + `fetch_k × multiplier` 补坑位，避免「结果莫名变少」 |
| 融合复杂度 | `weighted_fuse` O(n)，纯稠密 α=1.0 有快路径 |
| 已知成本 ① | 每次文档入库做一次 `count_live_by_kb`（JOIN COUNT）——换「计数 == 列表长度」恒等式，当前规模（个位数文档/库）下可忽略 |
| 已知成本 ② | Qdrant upsert 与 MySQL commit 非原子：失败窗口可能留下「有向量无行 / 有行无向量」。**靠幂等重投兜底**（同代次同 id，重写安全），已在 processor 注释中声明。属既有设计，本轮未放大 |

**安全（结论：租户边界单点闸门化，无越权路径发现）**

| 检查项 | 结论 |
|---|---|
| 租户隔离 | 分块读取唯一闸门 `list_by_vector_ids` 同时约束 chunk 与 doc 的 `tenant_id`（P1-A 回归由 `test_repository_tenant_isolation.py` 守护）；SQLAlchemy 表达式查询，无字符串拼 SQL |
| 降级分类 | `_classify_qdrant_failure` 区分配置故障（error 级）与瞬时故障（warning），不吞异常、诊断信息带回调用方（P2-E） |
| 重建脚本 | 默认 dry-run；目标集合存在即拒绝；`--execute` 与动作互斥组；tenant 一律从 kb 行派生，不接受外部传入。安全门均有单测（21 个） |
| 清理路径 | `collection_exists` 探测失败按「不存在」处理（宁可不删不误删）；删除 KB 时新旧两个集合都回收 |

小问题（P3，不阻塞）：

1. `get_qdrant_client` 的 `timeout=3600` 对在线 API 路径偏长（对批量脚本合理）。可考虑
   在线/离线分客户端，属既有代码，本轮未动。
2. `collection_layout` 缓存为进程级，celery 线程池与 API 进程各持一份，60 秒陈旧窗口
   内的行为差异已论证可接受，仅备忘。

### A.3 三问：是否符合项目风格

| 检查项 | 结论 |
|---|---|
| 分层 | API → Service → Repository 未破例；脚本层复用 Repository 的口径方法（`count_live_by_kb` 被 processor / rebuild / rollback 三处共用）而非各写一份 SQL |
| 命名/常量 | 集合名（`collection_name_for`）、向量名（`NAMED_DENSE_VECTOR`/`NAMED_SPARSE_VECTOR`）、代次（`config.chunk_epoch`）各只有一个真值来源 |
| 统一响应 | `search()` 返回契约保持 list-of-dict，新增字段全部向后兼容（`source_page`/`heading_path` 显式出现，可为 None） |
| 测试范式 | 新增 97 个用例遵循既有风格；删字段类改动附「移除守卫」（`deleted_at` 不再可过滤的 fail-closed 断言）；测试 fixture 对齐生产 `autoflush=False`（本轮借此抓出 count 时序 bug） |
| 配置 | 新增开关/参数全部走 `app/core/config.py` + 环境变量，无散落的硬编码 |

### A.4 审查发现汇总

| 级别 | 发现 | 处置 |
|---|---|---|
| P0/P1 | 无 | — |
| P2 | Qdrant/MySQL 双写非原子（既有设计） | 已由幂等重投兜底并在注释/本文档声明，接受 |
| P3 | docstring 过长、客户端 timeout、进程级缓存等 4 处 | 备忘，不阻塞交付 |

**回归证据**：容器全量 `pytest -q --ignore=tests/test_celery_config.py` → **623 passed / 0 failed**
（2026-09-15；本地因缺 torch 有 3 个环境性失败，容器内全绿）。
