from pathlib import Path
import os
from typing import Optional
from urllib.parse import quote, urlparse

from pydantic_settings import BaseSettings
from pydantic import SecretStr

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 允许在测试 / CI 环境下跳过 .env 读取。
# 默认行为不变（读取 backend/.env）；设置 AI_STUDIO_SKIP_ENV_FILE=1 时，
# 仅使用下方字段默认值与环境变量，从而让测试不依赖本机凭据文件——
# 否则任何缺少 .env 的环境都无法导入 app.core.config，整个测试套件在
# collection 阶段即失败。生产运行不受影响。
_SKIP_ENV_FILE: bool = os.environ.get('AI_STUDIO_SKIP_ENV_FILE', '').strip().lower() in {
    '1',
    'true',
    'yes',
    'on',
}
_ENV_FILE: Optional[str] = None if _SKIP_ENV_FILE else str(BASE_DIR / '.env')

#: 解析 / 分块**策略**版本号——只在「块边界算法」变化时递增。
#:
#: 为什么必须与 ``chunk_size`` / ``chunk_overlap`` 分开：代次（epoch）原本只由尺寸
#: 参数构成（``"448-64"``），而「改块边界」并不改尺寸参数。于是 P1（PDF 段落重建）
#: 与 P2（结构组合并）落地后，新旧两代会算出**同一个** epoch：
#:
#: * ``rebuild_knowledge_vectors.py`` 无法区分「当前代 / 可回收代」，旧分块行不会被回收；
#: * 检索**同时命中两代不同切法的块**，同一段内容以两种边界反复出现；
#: * ``kb.chunk_count`` 因按同一 epoch 过滤而**看起来正常**；
#: * 全程无任何报错或告警——纯粹的静默数据错误。
#:
#: 故凡改变块边界（解析层归一化、分组/合并规则、分隔符链）都必须递增此常量。
#: 它不参与运行时分支，只参与代次标识与唯一的 ``vector_id`` 命名空间。
#:
#: 版本历史
#: --------
#: * ``p0``——历史默认（无标签）；块边界由「一段一组的贪心装箱」决定。
#: * ``p1``——解析层契约对齐（PDF 段落重建，``\\n\\n`` 可达）+ 分块层结构组合并
#:   （顶层标题硬边界、短串并入下一串）+ 出处区间化（``page_end`` /
#:   ``heading_path_mixed``）。
#: * ``p2``——结构解析流水线（S1~S5）：PDF 标题/表格识别（版式信号 + 矢量线框）、
#:   DOCX/MD 表格与代码块原子化、分块层块类型驱动（表格/代码不可切碎、标题不孤儿）。
#:   分块边界与块类型均变化，必须换代次以触发全量重建。
#: * ``p3``——解析层缺陷修复：①表格质量守卫 + 线框检测规模上界 + 抹除面积保护
#:   （伪表格不再产出）；②代码判定改为**多信号加权**（解除整篇等宽门禁）+
#:   ``to_sections`` 补 code 成节规则（代码块恢复原子性）；③超长原子块降级切分
#:   （``ATOMIC_MAX_CHARS``，与嵌入上限对齐）。块边界再次变化，必须换代次。
CHUNK_STRATEGY_VERSION: str = 'p3'


class Config(BaseSettings):
    # MySQL
    database_type: str = 'mysql'
    connector: str = 'pymysql'
    database_host: str = 'localhost'
    database_port: int = 3306
    database_name: str = ''
    database_username: str = ''
    database_password: SecretStr = SecretStr('')
    database_socket: Optional[str] = None

    # Qdrant
    qdrant_url: str = 'http://localhost:6333'
    qdrant_api_key: str = ''   # 本地部署可留空，云端部署时填写

    # Redis
    redis_host: str = '127.0.0.1'
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: SecretStr = SecretStr('')

    # JWT
    jwt_secret_key: SecretStr = SecretStr('change-me-in-production')
    jwt_algorithm: str = 'HS256'
    jwt_access_token_expire_minutes: int = 5
    jwt_refresh_token_expire_days: int = 7

    # Encryption
    fernet_key: SecretStr = SecretStr('')

    # File upload
    upload_dir: str = '/tmp/ai_studio/uploads'
    max_upload_size_mb: int = 50

    # CORS：允许跨域访问的前端源（逗号分隔）。默认值为开发用 localhost:3000。
    # 标准部署中前端与 API 经 vite/nginx 同域代理，浏览器侧不触发跨域；
    # 仅当浏览器直接跨域访问后端时才需配置。设为空字符串表示拒绝任何跨域请求，
    # 杜绝原先 ``allow_origins=["*"]`` + ``allow_credentials=True`` 导致的凭证泄露风险
    # （详见 docs/review/01-backend.md S1）。
    cors_origins: str = 'http://localhost:3000'

    # Celery
    celery_broker_url: str = 'redis://localhost:6379/1'
    celery_result_backend: str = 'redis://localhost:6379/2'

    # 工作流执行整体超时（秒）。A3：防止单个工作流无限挂起占用请求。
    # 单点 LLM 调用另有客户端超时（utils/llm.py），此处约束整条 DAG 的执行预算。
    workflow_execution_timeout_seconds: int = 600

    # embedding
    # 默认使用本地 sentence-transformers 模型，保证企业内网数据不出网。
    # 如需切换外部 API，可将 embedding_provider 改为 openai/azure/siliconflow/ollama。
    embedding_provider: str = 'sentence-transformers'
    embedding_model: str = 'BAAI/bge-base-zh-v1.5'
    embedding_device: str = 'cpu'  # 本地模型推理设备：cpu / cuda
    embedding_api_key: SecretStr = SecretStr('')
    embedding_api_base: str = ''

    # 文档分块
    # 上限由**硬约束**决定：稠密模型与精排模型的 ``max_seq_length`` 均为 512 token
    # （bge-base-zh-v1.5 / bge-reranker-v2-m3），而 sentence-transformers 对超长输入
    # 是**静默截断**——不报错、不告警，超出部分从不进入向量，也从不进入精排。
    # 旧默认 1024 字符在本项目语料上实测：单块词元 p50=489 / p90=954 / max=1026，
    # **49.7% 的块超出 512 token，全库 28.3% 的词元从未被编码**。后果有三：
    # ① 块的后半段语义上不存在，检索不到；② 稠密分支只看到前半段、稀疏（BM25）
    # 分支看到全文，两路融合时口径不一致；③ 精排同样截断，等于用半块判相关性。
    # 448 是实测「零截断且留有安全余量」的取值：本语料 1 中文字 ≈ 1.075 token，
    # 448 字符 → 实测词元上限 450（余量 62 token ≈ 12%），足以吸收稀有汉字与中英
    # 混排；512 字符已在实测中出现 0.09% 截断，故不取。
    # 重叠比例 64/448 ≈ 14%，落在社区推荐区间（10%~20%）中部；重叠的代价很低
    # （实测 overlap=128 仅使块数 +10.7%），但跨块边界的答案必须靠它才能被单块
    # 完整支撑。**改动此二值会使既有向量失效**，需重建集合（见
    # scripts/index_rag_eval_corpus.py 与 docs/rag-eval/FIX-AND-HYBRID-RETRIEVAL-REPORT.md）。
    chunk_size: int = 448
    chunk_overlap: int = 64

    # 原子块（表格 / 代码）的长度上界。``None`` ⇒ 取 ``2 × chunk_size``（当前 896）。
    # 存在的理由：``is_atomic`` 承诺「不切碎」，而嵌入模型 ``max_seq_length=512``
    # （中文 ≈476 字）对超长输入是**静默截断**——实测 51 个 code chunk 中 23 个
    # （45%）超限、最长 1840 字符，超出部分从不进入向量。宁可切分，不可丢失。
    # 取 2 倍是为「函数级完整」留余量（实测代码块长度中位 330、p90 约 800）。
    atomic_max_chars: Optional[int] = None

    # 检索
    # 向量召回的相似度下限。0.0 表示不做阈值过滤，交由后续精排阶段裁量；
    # 调高可提升精确率但会漏召回，建议在评测集上标定后再调整。
    retrieval_score_threshold: float = 0.0

    # 检索结果去重
    # 同一段落在知识库中可能存在多份等值副本（同一文档被重复上传，或不同文档内容
    # 重合）。每个副本都是一个独立的 Qdrant point，会各自占据一个候选位，导致同一
    # 段落并列占满 top_k，并重复灌入 LLM 上下文。开启后按内容归一化折叠等值副本。
    retrieval_dedup_enabled: bool = True

    # 去重前的召回放大倍数。
    # 去重会折叠掉等值副本，被折叠的坑位必须靠超额召回补回，否则「top_k=10」在
    # 存在副本时只会返回更少条不同内容（表现为「结果条数莫名变少」）。该值直接
    # 放大 Qdrant 召回量与回表行数，需与延迟一并权衡。
    retrieval_fetch_multiplier: int = 2

    # 混合检索（稠密 + 词法双路，应用层加权分数融合）
    # **默认关闭**：混合检索的实测增益是 +1pp 量级的小幅提升，且它需要集合采用
    # 「命名稠密 + 命名稀疏」布局（既有集合必须回填或重建）才真正生效——对未回填的
    # 集合开启只会让稀疏分支空手而归。必须先在目标库上跑评测门禁再逐库开启。
    retrieval_hybrid_enabled: bool = False

    # 融合权重：``score = α·norm(dense) + (1−α)·norm(sparse)``。
    # 实测 α∈{0.6,0.7,0.8} 三点均优于纯稠密，0.7 最优；α=1.0 等价于关闭混合检索。
    # **不要用等权 RRF**：实测等权 RRF 使 MRR@10 −7.33pp、nDCG@10 −6.03pp
    # （词法分支显著弱于稠密，等权会让其噪声排名挤掉正确项）。
    retrieval_hybrid_alpha: float = 0.7

    # 混合检索时**每一路**的召回条数。
    # 两路各召回该数量后再融合，故实际候选量约为 2×；该值直接决定延迟与回表行数。
    retrieval_sparse_top_k: int = 50

    # 稀疏编码器的 BM25 参数。``k1``/``b`` 取文献默认值，一般无需调整。
    retrieval_sparse_k1: float = 1.2
    retrieval_sparse_b: float = 0.75
    # 无状态模式下的假定平均文档长度（词元数）。
    # 取值说明见 ``app/utils/sparse.py``：只影响长度归一化的相对强度，BM25 对其不敏感。
    # 该值是 ``chunk_size`` 的**派生量**，须随分块参数同步（当前 448 字符 → 实测 487 词元）。
    retrieval_sparse_avgdl: float = 490.0
    # 稀疏编码器是否使用 IDF。
    # 默认关闭（无状态）：同一文本在任意时刻、任意语料规模下编码结果一致，
    # 因此**支持增量入库**。开启后新增文档会使 df/avgdl 失效，必须整库重编码，
    # 增益约高 30%（实测 MRR@10 +1.20pp vs +0.93pp）。仅在离线回填/评测时开启。
    retrieval_sparse_idf_enabled: bool = False

    # 检索结果的「上下文装配」（P4）
    #
    # 分块尺寸与「喂给 LLM 的文本」是两个矛盾的目标：检索要小块（语义聚焦、命中
    # 精确），生成要大块（指代完整、出处可核对）。把块整体调大只会同时牺牲两者，
    # 正确做法是写入侧保持小块、读取侧在命中后补回上下文。
    #
    # 下面两个开关相互独立，都只影响新增的 ``llm_content`` 字段，**不修改
    # ``content``**——后者同时是去重键、前端展示文本与既有调用方的取值处。因此
    # 二者全部关闭时，检索结果的既有字段与改造前逐字节一致，这是本层的回滚开关。
    #
    # 上下文头：把「文件名 / 小节路径 / 页码范围」前置为一行出处标记，如
    # ``[《手册.pdf》 | § 3.2 学习路径 | p.37–38]``。收益是让模型能读到块的归属
    # （否则 PDF 块是无标题的裸文本），并让回答可直接给出可核对引用。
    retrieval_context_header_enabled: bool = True

    # 邻块扩展半径（``chunk_index ± N``，0 = 关闭）。
    # 用于修复「答案跨块」：一个问题的证据常分散在相邻 2–3 块（定义与例子、步骤
    # 与注意事项），单块命中时答案不完整。取 1 表示拼接前后各一块。
    # 取值直接决定喂给 LLM 的上下文体积（约 (2N+1)×块长）与回表行数，需与延迟、
    # token 预算一并权衡；块重叠部分会由 app/utils/retrieval_context 裁掉。
    retrieval_neighbor_expansion: int = 1

    # Reranker（本地 CrossEncoder 精排）
    # 默认关闭：精排会引入额外推理延迟，且不同知识库的最优候选数不同，
    # 必须在评测集上标定后再按知识库开启，不应默认对所有流量生效。
    reranker_enabled: bool = False
    reranker_model: str = 'BAAI/bge-reranker-v2-m3'
    reranker_device: str = 'cpu'   # 本地模型推理设备：cpu / mps / cuda
    # 宽召回候选数：精排只能对已召回的候选重排，候选集过小会限制精排的上限。
    # 该值直接决定延迟（精排成本与候选数线性相关），需与质量一并标定。
    reranker_candidate_k: int = 20
    reranker_batch_size: int = 32
    # 精排输入截断长度。过长会显著拖慢 CPU 推理，而中文段落的关键信息通常在前部。
    reranker_max_length: int = 512

    # Ollama
    ollama_base_url: str = 'http://localhost:11434'

    # 邮件（邮箱验证）。全部留空表示「不发送邮件」，由调用方走开发态回退
    # （注册/重发接口在响应中直接返回 verification_token 供本地联调）。
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: SecretStr = SecretStr('')
    smtp_use_tls: bool = True
    email_from: str = 'no-reply@ai-studio.local'
    # 前端基础地址，用于拼接邮箱验证链接
    app_frontend_base_url: str = 'http://localhost:3000'
    # 邮箱验证令牌有效期（小时）
    email_verification_ttl_hours: int = 24

    # LLM 请求超时（秒）。用于 openai / anthropic / azure / custom 等远端供应商：
    # 超时后由服务端主动失败并返回明确错误，避免请求长时间悬挂
    # （langchain-openai 默认 600s，前端会先于其超时）。
    # Ollama 本地推理较慢（首次调用需加载模型），单独走 600s，不由此值控制。
    llm_request_timeout: int = 120

    # 出站访问策略（SSRF 防护），作用于插件调用与 Agent 的 API 工具。
    # True（默认，安全基线）：拒绝访问私有地址、环回、链路本地（含云元数据
    #   169.254.169.254）、保留与组播网段，避免平台被用作 SSRF / 内网探测跳板。
    # 置为 False 会**关闭**该校验——仅在部署环境确需让插件访问内网服务
    #   （如对接内部 CRM / 私有 API）时使用，属有意识的降级，
    #   应同时通过网络层出站策略限制可达范围。详见 app/utils/net_guard.py
    plugin_block_private_network: bool = True

    def _with_redis_password(self, url: str) -> str:
        """URL 未携带凭据时注入 ``redis_password``。

        必须与 ``app/core/redis.py`` 的行为保持一致：该文件用 ``redis_password``
        认证，而 Celery 直接使用 ``celery_broker_url`` 原文。若部署时设置了
        ``REDIS_PASSWORD`` 但 ``CELERY_BROKER_URL`` 未内嵌密码，就会出现
        「Redis 客户端能连、Celery worker 报 NOAUTH」的分裂状态，表现为文档处理
        任务永远不被消费、状态卡在 pending，而日志里没有任何明显线索。
        """
        password = self.redis_password.get_secret_value()
        if not password or not url:
            return url
        parsed = urlparse(url)
        if parsed.password or not parsed.hostname:
            return url
        netloc = f"{parsed.username or ''}:{quote(password, safe='')}@{parsed.hostname}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()

    def get_celery_broker_url(self) -> str:
        """Celery broker 地址（必要时注入 Redis 密码）"""
        return self._with_redis_password(self.celery_broker_url)

    def get_celery_result_backend(self) -> str:
        """Celery 结果后端地址（必要时注入 Redis 密码）"""
        return self._with_redis_password(self.celery_result_backend)

    @property
    def cors_origins_list(self) -> list:
        """解析 CORS 允许源为列表；空字符串返回空列表（拒绝任何跨域）。"""
        return [o.strip() for o in self.cors_origins.split(',') if o.strip()]

    @property
    def chunk_epoch(self) -> str:
        """分块代次标识，形如 ``"448-64-p1"``。

        三个分量**缺一不可**：``chunk_size`` / ``chunk_overlap`` 描述尺寸预算，
        ``CHUNK_STRATEGY_VERSION`` 描述块边界算法（见该常量的说明——它补的正是
        「改了切法却没改尺寸」这一代次盲区）。

        分块参数或切法一旦变化，由旧参数产生的向量即**全部失效**，而新旧两代分块行在
        重建期间需要同时存活（旧行支撑回滚窗口）。代次就是这个「哪一代」的标识，
        它同时用在三处、必须**只有这一个定义**：

        1. ``KnowledgeChunk.chunk_epoch`` 列的默认值（每行自述属于哪一代）；
        2. ``vector_id`` 的命名空间后缀（``uuid5(..., f"{doc_id}_{index}@{epoch}")``）
           ——让新旧两代的分块 id 天然不同，从而不撞 ``vector_id`` 唯一索引；
        3. 重建脚本判定「当前代 / 可回收代」。

        三处若各写各的，重建就会出现「算了新代次、却把旧行标成新代次」这类
        静默错配，故收敛到配置层。
        """
        return f'{self.chunk_size}-{self.chunk_overlap}-{CHUNK_STRATEGY_VERSION}'

    model_config = {'env_file': _ENV_FILE}


config = Config()
