"""P3：分块出处区间化（页码区间 + 标题粗化标记）

一次迁移完成两件事（对应 docs/plan-chunking-structure-alignment.md §4-P2 的元数据升级）：

1. ``knowledge_chunks.source_page_end``——块覆盖页码的**结束页**；
2. ``knowledge_chunks.heading_path_mixed``——``heading_path`` 是否**粗于**本块的
   实际覆盖范围。

为什么出处要从「单值」升级为「区间」
------------------------------------

P2 引入**结构组合并**（顶层标题为硬边界、长度不达标的串并入下一串）之后，一个块可以
跨越多个段，于是：

* ``source_page`` 单独一个值只能表达「从哪一页开始」，前端显示「第 37 页」而块里
  其实含有第 38 页的开头——**沉默的错答**。加上 ``source_page_end`` 才可以说
  「第 37–38 页」；
* 合并 ``A`` 与其子节 ``A > B`` 时 ``heading_path`` 收敛为 ``A``，这是**精确**的
  （块确实含 A 自身的内容）；但合并 ``A > B`` 与 ``A > C`` 时只能标成公共祖先
  ``A``，而块里**没有** A 自身的内容——这是**粗化**。两者用一个字段表达会导致
  前端无法区分，故用 ``heading_path_mixed`` 单独标记后者。

``heading_path_mixed`` 判据的教训
---------------------------------

实现时最初按「组内标题路径多于一个」判定，结果在真实语料上 **19/19 全为真**、彻底
失去区分度（父节 + 其子节的合并是常态，而它不是「粗化」）。正确判据是
「公共前缀**不在**组成员的路径集合里」。此列因此必须与 ``heading_path`` 一起看，
脱离后者单独解读会得出错误结论。

回填策略（幂等）
----------------

* ``source_page_end``：按「旧块不跨段」回填为 ``source_page``。旧的贪心分组虽然
  可能把多段并进一个组，但组的长度上限就是 ``chunk_size``，组尾残块确实可能跨段；
  不过**旧代次（1024-0 / 448-64）行即将被全量重建替换**，此处取等值是「无信息时
  不编造」的最保守选择；
* ``heading_path_mixed``：回填为 ``False``（旧实现无此概念，且旧块均出自单一标题
  路径，等价于「精确」）。

幂等性：MySQL DDL 非事务，失败可能已部分生效，故所有 DDL 均先 ``_has_column``
探测再执行；数据回填均带 ``WHERE`` 条件，可安全重跑。

Revision ID: k5l6m7n8o9p1
Revises: j4k5l6m7n8o9
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "k5l6m7n8o9p1"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """检查列是否存在，使本迁移可幂等重跑（MySQL DDL 非事务，失败可能已部分生效）。"""
    bind = op.get_bind()
    return column in {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    # 1) 结束页。可空：非 PDF 恒为 NULL，PDF 单页块等于起始页。
    if not _has_column("knowledge_chunks", "source_page_end"):
        op.add_column(
            "knowledge_chunks",
            sa.Column("source_page_end", sa.Integer(), nullable=True),
        )
        # 存量行「无区间信息」，最保守的取值是不编造：单页块就是结束页 == 起始页。
        op.execute(
            sa.text(
                "UPDATE knowledge_chunks SET source_page_end = source_page "
                "WHERE source_page_end IS NULL AND source_page IS NOT NULL"
            )
        )

    # 2) 标题粗化标记：先加可空列 → 回填 → 再收紧为 NOT NULL。
    #    三态会让「未设置」与「精确」不可区分，而库中绝大多数行本来就是精确的。
    if not _has_column("knowledge_chunks", "heading_path_mixed"):
        op.add_column(
            "knowledge_chunks",
            sa.Column("heading_path_mixed", sa.Boolean(), nullable=True),
        )
        op.execute(
            sa.text(
                "UPDATE knowledge_chunks SET heading_path_mixed = 0 "
                "WHERE heading_path_mixed IS NULL"
            )
        )
    # ``existing_type`` 对 MySQL 是**必填**：缺省会报
    # "All MySQL CHANGE/MODIFY COLUMN operations require the existing type"，
    # 且该错误会让整个迁移静默不落库（本项目已有前车之鉴）。
    op.alter_column(
        "knowledge_chunks",
        "heading_path_mixed",
        existing_type=sa.Boolean(),
        nullable=False,
    )


def downgrade() -> None:
    if _has_column("knowledge_chunks", "heading_path_mixed"):
        op.drop_column("knowledge_chunks", "heading_path_mixed")
    if _has_column("knowledge_chunks", "source_page_end"):
        op.drop_column("knowledge_chunks", "source_page_end")
