"""分块质量报告脚本的可执行性回归测试。"""

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "chunking_quality_report.py"


def test_chunking_quality_report_is_valid_python():
    """报告脚本必须能被 Python 编译，避免运行时才发现格式化字符串语法错误。"""
    source = SCRIPT.read_text(encoding="utf-8")
    compile(source, str(SCRIPT), "exec")
