"""env 文件卫生检查：防止「空值 + 行内注释」把注释读成配置值。

背景（真实缺陷，2026-09-12 排查）
--------------------------------

`backend/.env` 曾写成::

    QDRANT_API_KEY=              # 本地部署可留空；云端部署时填写

`python-dotenv` 对**空值**后的 `#` 不做注释剥离——注释整段成为配置值。于是
`qdrant_api_key` 变成字符串 ``"# 本地部署可留空；云端部署时填写"``，被
`QdrantClient` 当作 HTTP header 传入，`httpx` 在构造请求头时按 ASCII 编码失败::

    UnicodeEncodeError: 'ascii' codec can't encode characters in position 2-16

后果是**整轮评测 100 条查询全部失败**，且 CLI 的失败计数是「查询数 0、失败 100」，
指标全为 0，看起来像「检索效果极差」而非「配置读错」。

值得注意的对照：同一文件里 ``DATABASE_SOCKET=/tmp/mysql.sock   # 注释`` 是
**安全**的——`#` 之前有非空值，dotenv 会正常剥离行内注释。所以该缺陷只在
「空值键」上触发，隐蔽性强。

本测试把这条约定固化下来：任何配置文件里，解析后的值都不应以 ``#`` 开头。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent

#: 版本受控的模板必须存在；`.env` 属本地文件，缺失时跳过（CI 不提供）。
TEMPLATE = BACKEND_DIR / ".env.example"
LOCAL = BACKEND_DIR / ".env"


def _candidate_files() -> list[Path]:
    files = [TEMPLATE]
    if LOCAL.exists():
        files.append(LOCAL)
    return files


@pytest.mark.parametrize("path", _candidate_files(), ids=lambda p: Path(p).name)
def test_no_inline_comment_leaks_into_value(path: Path) -> None:
    """解析后的值不得以 ``#`` 开头——那说明注释被当成了配置值"""
    values = dotenv_values(path)
    leaked = {key: value for key, value in values.items() if value and value.lstrip().startswith("#")}
    assert not leaked, (
        f"{path.name} 存在「空值 + 行内注释」写法，注释被读成了配置值：{leaked}。"
        "请把注释单独成行，或写成 `KEY=value  # 注释`（值非空时 dotenv 才会剥离注释）。"
    )


def test_template_values_are_ascii() -> None:
    """模板文件的值必须是 ASCII

    模板中的值会被复制到真实配置，进而可能进入 HTTP header / URL；这类位置按
    ASCII（上限 latin-1）编码，非 ASCII 会在很晚的阶段才以难以定位的
    ``UnicodeEncodeError`` 暴露。模板层做静态约束，成本最低。
    """
    values = dotenv_values(TEMPLATE)
    offenders = {
        key: value
        for key, value in values.items()
        if value and any(ord(char) > 127 for char in value)
    }
    assert not offenders, f"{TEMPLATE.name} 含非 ASCII 配置值：{offenders}"
