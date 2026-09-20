"""``kind -> chunk_type`` 映射的契约（P1 类型贯通）

**为什么要单独一个文件**：``chunk_type`` 是解析层与前端之间**唯一的**类型契约，
而它与 ``kind`` 的取值域**并不相同**——``kind`` 有十余种（``paragraph`` /
``list_item`` / ``caption`` / ``toc`` / ``heading`` …），``chunk_type`` 只有五种。
两者之间必须有显式映射，而「映射写在哪里」这件事本身就是缺陷来源：

* 写两遍（入库服务一份、重建脚本一份）⇒ 两份迟早分叉，且**分叉是静默的**：
  两条写入路径各自都能通过自己的测试，只有「先跑重建、再跑重新上传」才会看出
  同一篇文档的 ``chunk_type`` 不一样；
* 直接透传 ``chunk.kind`` ⇒ ``toc`` / ``caption`` 这类值静默入库。列是
  ``String(16)``，不会拒绝它们，但前端从未适配过——渲染分支会落到默认分支，
  而默认分支恰好是「按正文渲染」，于是缺陷表现为「表格看起来是纯文本」，
  正是本轮的原始报障。

因此本文件盯三件事：**取值域闭合**、**列宽可信**、**映射只有一处**。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.utils.document import (
    CHUNK_TYPES,
    _KIND_TO_CHUNK_TYPE,
    chunk_type_for,
)

#: 解析层**实际会产出的** ``kind`` 全量（来源见下），用于给映射表定界。
#:
#: * ``structure_blocks.classify_line``：``toc`` / ``caption`` / ``code`` /
#:   ``title`` / ``heading`` / ``list_item`` / ``paragraph``，外加
#:   ``to_sections`` 直接构造的 ``table``；
#: * ``document.parse_markdown_segments`` / ``parse_docx_segments``：``heading`` /
#:   ``paragraph`` / ``code`` / ``table``；
#: * ``image`` 为 P2-a 图片锚点预留（解析层尚未产出）。
PARSER_KINDS = frozenset(
    {
        "paragraph",
        "heading",
        "title",
        "code",
        "table",
        "list_item",
        "caption",
        "toc",
        "image",
    }
)

#: 列宽上界，与 ``app/models/knowledge_chunk.py`` 的 ``String(16)`` 对齐。
#: 写死在这里是刻意的：若哪天有人把这个值改大，测试不会跟着松掉——列宽变化应当
#: 是一次**有意识的**改动，而不是被测试自动接受。
COLUMN_MAX_CHARS = 16


class TestValueDomain:
    def test_every_mapping_target_is_declared(self):
        """映射表的**值**必须全部落在 ``CHUNK_TYPES`` 内

        这是「取值域闭合」的判据。映射值多出一个未声明的类型时，前端会拿到一个
        它不认识的 ``chunk_type`` 并落到默认渲染分支——而默认分支是正文渲染，
        于是新类型**看起来永远没生效**。
        """
        assert set(_KIND_TO_CHUNK_TYPE.values()) <= CHUNK_TYPES

    def test_mapping_keys_are_real_parser_kinds(self):
        """映射表的**键**必须是解析层真实会产出的 ``kind``

        防的是拼写错误：``"headings"`` / ``"list-item"`` 这类值不会报错，只会
        永远匹配不上，表现为「该类型的块恒为 ``text``」。
        """
        assert set(_KIND_TO_CHUNK_TYPE) <= PARSER_KINDS

    def test_unknown_kind_falls_back_to_text(self):
        """未知 ``kind`` 一律回落 ``text``：宁可少标，也不能写入取值域外的值"""
        assert chunk_type_for("something-new") == "text"
        assert chunk_type_for("") == "text"

    def test_all_values_fit_column_width(self):
        """每个取值都要放得进 ``String(16)``

        MySQL 在严格模式下会直接报错，而在非严格模式下会**静默截断**——
        后者会让 ``chunk_type`` 变成一个无法与任何已知类型匹配的残值。
        """
        too_long = {t for t in CHUNK_TYPES if len(t) > COLUMN_MAX_CHARS}
        assert not too_long, f"超出列宽的取值: {too_long}"


class TestMappingTable:
    @pytest.mark.parametrize(
        "kind, expected",
        [
            # 需要前端换渲染分支的三类：必须原样透传
            ("code", "code"),
            ("table", "table"),
            ("title", "title"),
            # 标题层级归一：渲染分支相同，层级信息由 heading_path 承担
            ("heading", "title"),
            # 界面上都只是正文段落：单独建值只会给前端添永不触发的分支
            ("paragraph", "text"),
            ("list_item", "text"),
            ("caption", "text"),
            ("toc", "text"),
            # P2-a 预留
            ("image", "image"),
        ],
    )
    def test_expected_mapping(self, kind, expected):
        assert chunk_type_for(kind) == expected

    def test_only_structural_types_are_distinguished(self):
        """非 ``text`` 的取值只有四种：多出来的必然是误加的分支

        这条是**反向守卫**：它不检查某个具体映射，而是检查「被区别对待的类型
        集合」没有悄悄变大。新增一种需要独立渲染的类型应当是显式决策，
        伴随前端渲染分支与迁移口径确认。
        """
        distinguished = {v for v in _KIND_TO_CHUNK_TYPE.values() if v != "text"}
        assert distinguished == {"code", "table", "title", "image"}


class TestSingleSourceOfTruth:
    """映射只能有一份实现

    要求「只有一处」而不是「两处行为一致」：两份实现的一致性**无法被测试长期
    保证**（需要穷举两份的输入空间），而一处实现的一致性不需要测试——它由语言
    的语义保证。
    """

    def test_ingest_service_uses_shared_mapping(self):
        from app.services import knowledge_processor

        src = inspect.getsource(knowledge_processor)
        assert "chunk_type=chunk_type_for(chunk.kind)" in src

    def test_rebuild_script_uses_shared_mapping(self):
        """重建脚本与新文档入库必须走同一份映射

        脚本用 ``read_text`` 断言而不导入模块：脚本带 ``sys.path`` 副作用与
        ``if __name__`` 守卫，导入它只为读两行源码并不划算（
        ``test_rebuild_knowledge_vectors.py`` 已用 ``importlib`` 完整加载它，
        那条路径覆盖的是行为，这里覆盖的是**来源**）。
        """
        script = (
            Path(__file__).resolve().parent.parent / "scripts" / "rebuild_knowledge_vectors.py"
        )
        src = script.read_text(encoding="utf-8")
        assert "chunk_type=chunk_type_for(chunk.kind)" in src
        # 迁移守卫：脚本内**不得**再有第二份映射实现（曾存在 ``_chunk_type_of``）
        assert "def _chunk_type_of" not in src
