"""Phase 5: 分块元数据落位 + 取消分块软删

一次迁移完成五件事（方案 §3.1，合并 5.4 / 5.6 / 5.8 的公共前置）：

1. ``knowledge_chunks.heading_path``——D12 标题路径（md / docx 可得，PDF 留空）；
2. ``knowledge_chunks.chunk_epoch``——**该行由哪一代分块参数产出**，取值
   ``"{chunk_size}-{chunk_overlap}"``；
3. ``knowledge_documents.active_chunk_epoch``——**该文档当前生效的是哪一代**；
4. ``knowledge_bases.active_collection``——灰度 / 回滚指针；
5. **删除 ``knowledge_chunks.deleted_at``**（取消分块软删），并在删列前物理清除
   既有的 905 行墓碑记录。

为什么取消分块软删：

* **分块是派生数据**：它是「上传原件 + 解析器 + 分块参数 + 嵌入模型」的确定性函数，
  重算即可得。软删的适用对象是**不可再生**的数据（用户原创内容、账务、审计），
  套在派生索引上只带来成本、不带来能力。
* **软删语义已自相矛盾**：删除文档时 Qdrant 侧的点是被**硬删**的，而 MySQL 行却
  标记为「已软删」——该行既不可恢复（向量已不存在）、也不可检索，只剩一个墓碑。
* **唯一索引 + 软删是公认反模式**：``vector_id`` 上有唯一索引，软删不释放该值。
  实测 1206 行中 **905 行为墓碑**（占 3/4），重建沿用同一 ``doc.id`` 与序号时
  新旧 id 相同，插入必然 ``IntegrityError``。MySQL 下 ``(vector_id, deleted_at)``
  复合索引**并不能**解决问题（NULL 互不相等，等于没有唯一性约束），
  要救必须造生成列——为一个自设限制打的补丁。
* **读取侧必须人人记得过滤**：``deleted_at IS NULL`` 在仓储层出现 8 处，
  这正是本项目 P1-A / D9 两次事故的成因（漏一处即「已下架内容仍被检索命中」）。
  列不存在后，此类漏写在构造上不可能发生（fail-closed）。

### 为什么必须同时引入「代次」两列（而不是只删软删）

软删原本**顺带**承担了一个职责：标记「上一代分块」。取消它之后，重建期间同时存活的
新旧两代分块行就无从区分，而三件事都依赖这个区分：

* **验收计数**：`kb.chunk_count` 应等于「当前代存活分块数」，两代共存时
  ``COUNT(*)`` 会把 301 行旧代一起算进去；
* **回滚窗口**：旧代行必须留着，否则把 ``active_collection`` 指回旧集合后，
  检索命中的 ``vector_id`` 在库里查不到内容，回滚等于把检索打断；
* **旧代回收**：没有可查询的代次，就没有安全的 GC 判据。

两列分工明确：分块上的 ``chunk_epoch`` 是**自述**（这一行是谁产出的），
文档上的 ``active_chunk_epoch`` 是**权威**（这份文档现在该看哪一代）。
后者**不能**用 ``config.chunk_epoch`` 代替——配置在重建前就已变成新值，
拿它过滤会让该文档的分块列表在重建完成前静默返回空。

墓碑行清理的安全性（删列前先删行，否则这些行会立刻"装扮成存活行"污染计数与回读）：

* 实测 905/905 行全部挂在**已软删文档**上（3 份重复上传的 Happy-LLM-0727.pdf
  + 2 份探针文档），对应的 Qdrant 向量在删除文档时已一并硬删；
* 因此删除它们**不使任何可检索内容消失**，文档行本身保留，审计链完整；
* 迁移前已导出 dump：``backend/data/backups/20260915/pre-drop-soft-delete.sql``。

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "i3j4k5l6m7n8"
down_revision = "h2i3j4k5l6m7"
branch_labels = None
depends_on = None


#: 存量分块是旧参数（chunk_size=1024、重叠实际为 0）的产物。
#: 「重叠为 0」不是笔误：D11 使声明的 128 从未生效，重跑 1024/0 得到 301 块，
#: 与库中 ``chunk_count=301`` 逐数吻合，故存量行的真实代次就是 ``1024-0``。
LEGACY_CHUNK_EPOCH = "1024-0"


def _has_column(table: str, column: str) -> bool:
    """检查列是否存在，使本迁移可幂等重跑（MySQL DDL 非事务，失败可能已部分生效）。"""
    bind = op.get_bind()
    return column in {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    # 1) 先清墓碑：必须在删列之前，否则 ``deleted_at`` 一旦消失，
    #    这些行就与存活行无从区分。
    if _has_column("knowledge_chunks", "deleted_at"):
        op.execute(
            sa.text("DELETE FROM knowledge_chunks WHERE deleted_at IS NOT NULL")
        )

    # 2) 分块标题路径
    if not _has_column("knowledge_chunks", "heading_path"):
        op.add_column(
            "knowledge_chunks",
            sa.Column("heading_path", sa.String(length=512), nullable=True),
        )

    # 3) 分块代次：先加可空列 → 回填 → 再收紧为 NOT NULL。
    #    NOT NULL 是刻意的：GC 用 ``chunk_epoch <> 当前代`` 判定可清理行，
    #    若允许 NULL，忘写代次的行将永远无法被回收，成为新的隐性泄漏。
    if not _has_column("knowledge_chunks", "chunk_epoch"):
        op.add_column(
            "knowledge_chunks",
            sa.Column("chunk_epoch", sa.String(length=32), nullable=True),
        )
        op.execute(
            sa.text(
                "UPDATE knowledge_chunks SET chunk_epoch = :epoch "
                "WHERE chunk_epoch IS NULL"
            ).bindparams(epoch=LEGACY_CHUNK_EPOCH)
        )
    # ``existing_type`` 对 MySQL 是**必填**：缺省会报
    # "All MySQL CHANGE/MODIFY COLUMN operations require the existing type"，
    # 且该错误会让整个迁移静默不落库（本项目已有前车之鉴）。
    op.alter_column(
        "knowledge_chunks",
        "chunk_epoch",
        existing_type=sa.String(length=32),
        nullable=False,
    )

    # 4) 文档的当前代次。可空：NULL 表示「从未产出过分块」。
    #    只回填确有过分块的文档，避免给从未处理的文档编造代次。
    if not _has_column("knowledge_documents", "active_chunk_epoch"):
        op.add_column(
            "knowledge_documents",
            sa.Column("active_chunk_epoch", sa.String(length=32), nullable=True),
        )
        op.execute(
            sa.text(
                "UPDATE knowledge_documents AS d SET d.active_chunk_epoch = :epoch "
                "WHERE d.active_chunk_epoch IS NULL "
                "AND EXISTS (SELECT 1 FROM knowledge_chunks AS c WHERE c.doc_id = d.id)"
            ).bindparams(epoch=LEGACY_CHUNK_EPOCH)
        )

    # 5) 灰度 / 回滚指针
    if not _has_column("knowledge_bases", "active_collection"):
        op.add_column(
            "knowledge_bases",
            sa.Column("active_collection", sa.String(length=80), nullable=True),
        )

    # 6) 建代次索引：GC 与「按代计数」都以 (doc_id, chunk_epoch) 为谓词
    bind = op.get_bind()
    existing_indexes = {i["name"] for i in inspect(bind).get_indexes("knowledge_chunks")}
    if "ix_knowledge_chunks_doc_id_chunk_epoch" not in existing_indexes:
        op.create_index(
            "ix_knowledge_chunks_doc_id_chunk_epoch",
            "knowledge_chunks",
            ["doc_id", "chunk_epoch"],
            unique=False,
        )

    # 7) 最后删列
    if _has_column("knowledge_chunks", "deleted_at"):
        op.drop_column("knowledge_chunks", "deleted_at")


def downgrade() -> None:
    """恢复列结构，但不还原墓碑行（已物理删除，需要请从 dump 恢复）。

    ``deleted_at`` 一律回填为 NULL：降级后所有存活分块都应被视作有效，
    这与升级前的语义（存活行 ``deleted_at IS NULL``）一致。
    """
    bind = op.get_bind()
    existing_indexes = {i["name"] for i in inspect(bind).get_indexes("knowledge_chunks")}
    if "ix_knowledge_chunks_doc_id_chunk_epoch" in existing_indexes:
        op.drop_index("ix_knowledge_chunks_doc_id_chunk_epoch", table_name="knowledge_chunks")

    if not _has_column("knowledge_chunks", "deleted_at"):
        op.add_column(
            "knowledge_chunks",
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )

    if _has_column("knowledge_bases", "active_collection"):
        op.drop_column("knowledge_bases", "active_collection")

    if _has_column("knowledge_documents", "active_chunk_epoch"):
        op.drop_column("knowledge_documents", "active_chunk_epoch")

    if _has_column("knowledge_chunks", "chunk_epoch"):
        op.drop_column("knowledge_chunks", "chunk_epoch")

    if _has_column("knowledge_chunks", "heading_path"):
        op.drop_column("knowledge_chunks", "heading_path")
