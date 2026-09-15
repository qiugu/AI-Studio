"""签名一致性回归测试（防 A1 类缺陷复发）

**背景**：``KnowledgeBaseService.search`` 的参数名曾是 ``query_text``，
而 ``agent.py`` 与 ``workflow_engine.py`` 两处调用点传入 ``query``。
Python 对未知关键字参数直接抛 ``TypeError``，且该异常位于工具/节点内部，
表现为「知识库检索返回空」而非报错——**Agent 知识库工具与 Workflow 知识库
节点在修复前完全不可用**，而 REST 检索接口却正常，因此长期未被发现。

这类缺陷的共同特征是「跨文件的契约漂移」：本文件用 AST 全量扫描代替人工核对，
把契约一致性变成可自动验证的不变量。
"""

import ast
import inspect
from pathlib import Path
from typing import List, Set

import pytest

from app.services.knowledge import KnowledgeBaseService

APP_DIR = Path(__file__).resolve().parent.parent / "app"

#: 用于识别「这是知识库检索调用」的关键字参数
_KB_MARKER_KWARGS = {"kb_id", "query", "query_text", "top_k", "score_threshold"}


#: 承载知识库检索的方法名。
#: ``search_with_diagnostics`` 是实际实现；``search`` 是只返回结果列表的兼容包装。
#: 两者都必须纳入扫描——否则「把调用点从 search 迁到 search_with_diagnostics」会让
#: 本文件的扫描静默失效（契约漂移正是本文件要防的那类缺陷）。
_SEARCH_METHODS = ("search", "search_with_diagnostics")


def _accepted_params(method_name: str) -> Set[str]:
    """指定检索方法实际接受的参数名"""
    signature = inspect.signature(getattr(KnowledgeBaseService, method_name))
    return {name for name in signature.parameters if name != "self"}


def _iter_calls_with_kwargs() -> List[tuple]:
    """扫描 app/ 下全部检索调用，返回 (文件, 行号, 方法名, 关键字集合)"""
    found = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in _SEARCH_METHODS:
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            if kwargs & _KB_MARKER_KWARGS:
                found.append((path.relative_to(APP_DIR), node.lineno, func.attr, kwargs))
    return found


def test_search_accepts_query_keyword():
    """契约本身：检索方法必须接受 ``query``"""
    assert "query" in _accepted_params("search_with_diagnostics")


def test_search_does_not_accept_legacy_query_text():
    """契约本身：不得再保留 ``query_text``，否则两种写法并存会再次漂移"""
    for method_name in _SEARCH_METHODS:
        assert "query_text" not in _accepted_params(method_name)


def test_wrapper_signature_matches_implementation():
    """兼容包装与实现的参数集合必须完全一致

    否则「把调用点迁到包装方法」这一动作会引入参数不匹配，而失败点又在包装内部，
    排查成本与 A1 类缺陷相同。
    """
    assert _accepted_params("search") == _accepted_params("search_with_diagnostics")


def test_all_search_call_sites_match_signature():
    """全量扫描：所有知识库检索调用点的关键字必须都在被调方法的签名内"""
    violations = []
    for relative, lineno, method_name, kwargs in _iter_calls_with_kwargs():
        extra = kwargs - _accepted_params(method_name)
        if extra:
            violations.append(
                f"{relative}:{lineno} 调用 {method_name} 传入了签名外的关键字 {sorted(extra)}"
            )
    assert violations == [], "检索调用点与签名不一致：\n" + "\n".join(violations)


def test_scan_actually_covers_call_sites():
    """防止扫描本身失效：若调用点没扫到，上面的测试就是空转通过

    已知调用点：`services/agent.py`（Agent 知识库工具）与
    `services/workflow_engine.py`（Workflow 知识库节点）。
    """
    call_sites = _iter_calls_with_kwargs()
    assert len(call_sites) >= 2, f"未扫描到预期的调用点，实际：{call_sites}"
    covered = {str(relative) for relative, _, _, _ in call_sites}
    assert {"services/agent.py", "services/workflow_engine.py"} <= covered, (
        f"扫描未覆盖已知调用点，实际：{sorted(covered)}"
    )


def test_search_docstring_documents_types():
    """文档字符串需说明 kb_id 为 UUID 字符串——类型注解曾误写为 int

    详细说明随实现迁至 ``search_with_diagnostics``（``search`` 现为兼容包装），
    因此校验承载实现的那个方法。
    """
    docstring = inspect.getdoc(KnowledgeBaseService.search_with_diagnostics) or ""
    assert "kb_id" in docstring
    assert "query" in docstring


@pytest.mark.parametrize(
    "module_path, forbidden_snippets",
    [
        ("services/agent.py", ("query_text=",)),
        ("services/workflow_engine.py", ("query_text=",)),
    ],
)
def test_legacy_keyword_absent_from_source(module_path: str, forbidden_snippets: tuple):
    """源码级兜底：调用点不得残留历史参数名（含被注释掉的可疑写法）"""
    source = (APP_DIR / module_path).read_text(encoding="utf-8")
    for snippet in forbidden_snippets:
        assert snippet not in source, f"{module_path} 仍存在 {snippet}"
