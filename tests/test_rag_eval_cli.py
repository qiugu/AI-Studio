"""评测 CLI 端到端测试（子进程执行，覆盖真实的命令行入口）

以子进程方式验证而非直接导入模块，理由是 CLI 的关键契约是**进程行为**：
退出码、stdout 摘要、落盘文件名。这些都无法通过单元级调用验证。

注意：子进程必须显式传入 ``AI_STUDIO_SKIP_ENV_FILE=1``（与 ``conftest.py`` 对
主进程的做法一致），否则 CLI 会尝试读取本机 ``backend/.env``。

同时**强制离线**（``HF_HUB_OFFLINE=1`` / ``TRANSFORMERS_OFFLINE=1``）：本模块所有
用例都使用 ``in-memory`` 检索器与离线夹具，本就不应触网。曾出现真实故障——
``test_rerank_reports_unavailable_model`` 指望「模型路径不存在 → 快速失败」，
而未缓存的模型 id 会先触发 huggingface_hub 的 HEAD 探测（10 s 超时 × 5 次重试 ×
多个文件），在无外网环境下把用例拖到超时。测试的成败不应取决于网络可达性。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
CLI = BACKEND_DIR / "scripts" / "rag_eval.py"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rag_eval"
TIMEOUT_SECONDS = 120
#: 需要 import torch / sentence-transformers 的用例专用预算。
#: 该导入链在本机沙箱下约 90 秒（见 ``test_rerank_reports_unavailable_model``）。
HEAVY_TIMEOUT_SECONDS = 300


def _run_cli(*args: str, timeout: int = TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["AI_STUDIO_SKIP_ENV_FILE"] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        cwd=str(BACKEND_DIR),
    )


@pytest.fixture(scope="module")
def smoke_report(tmp_path_factory) -> tuple[subprocess.CompletedProcess, Path]:
    out_dir = tmp_path_factory.mktemp("rag_eval_reports")
    result = _run_cli(
        "--retriever",
        "in-memory",
        "--golden",
        str(FIXTURE_DIR / "golden.jsonl"),
        "--corpus",
        str(FIXTURE_DIR / "corpus.jsonl"),
        "--name",
        "cli-smoke",
        "--out-dir",
        str(out_dir),
    )
    return result, out_dir


class TestHelp:
    def test_help_works_without_loading_config(self):
        """--help 必须能在不加载本机配置的情况下返回 0（导入已延迟到参数解析之后）"""
        result = _run_cli("--help")
        assert result.returncode == 0
        assert "usage: rag_eval" in result.stdout
        assert "--candidate-k" in result.stdout


class TestSmokeRun:
    def test_exit_code_and_summary(self, smoke_report):
        result, _ = smoke_report
        assert result.returncode == 0, result.stderr
        assert "运行：cli-smoke" in result.stdout
        assert "覆盖率校验通过" in result.stdout

    def test_reports_written(self, smoke_report):
        _, out_dir = smoke_report
        assert (out_dir / "cli-smoke.json").exists()
        assert (out_dir / "cli-smoke.md").exists()

    def test_json_metrics_match_fixture_expectation(self, smoke_report):
        """夹具语料下 recall@3 应为 1.0（6 条查询全部在前 3 位命中）"""
        _, out_dir = smoke_report
        payload = json.loads((out_dir / "cli-smoke.json").read_text(encoding="utf-8"))
        assert payload["n_scored"] == 6
        assert payload["n_failed"] == 0
        assert payload["aggregate"]["recall@3"] == pytest.approx(1.0)

    def test_markdown_has_comparison_ready_sections(self, smoke_report):
        _, out_dir = smoke_report
        markdown = (out_dir / "cli-smoke.md").read_text(encoding="utf-8")
        assert "## 总体指标" in markdown
        assert "## 数据集与可复现性" in markdown


class TestRegressionGateCLI:
    def test_regression_fails_build_when_flagged(self, tmp_path):
        """门禁不通过且带 --fail-on-regression 时退出码必须为 1（供 CI 使用）"""
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(
            json.dumps({"name": "base", "aggregate": {"recall@1": 1.0}}),
            encoding="utf-8",
        )
        result = _run_cli(
            "--retriever",
            "in-memory",
            "--golden",
            str(FIXTURE_DIR / "golden.jsonl"),
            "--corpus",
            str(FIXTURE_DIR / "corpus.jsonl"),
            "--name",
            "cli-gate-fail",
            "--out-dir",
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--gate-metric",
            "recall@1",
            "--max-drop-pp",
            "0.0",
            "--fail-on-regression",
        )
        assert result.returncode == 1
        assert "门禁 recall@1" in result.stdout
        assert "不通过" in result.stdout

    def test_regression_non_fatal_without_flag(self, tmp_path):
        """未显式要求时，门禁失败只提示、不改变退出码，避免误伤本地调试"""
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(
            json.dumps({"name": "base", "aggregate": {"recall@1": 1.0}}),
            encoding="utf-8",
        )
        result = _run_cli(
            "--retriever",
            "in-memory",
            "--golden",
            str(FIXTURE_DIR / "golden.jsonl"),
            "--corpus",
            str(FIXTURE_DIR / "corpus.jsonl"),
            "--name",
            "cli-gate-warn",
            "--out-dir",
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--gate-metric",
            "recall@1",
            "--max-drop-pp",
            "0.0",
        )
        assert result.returncode == 0
        assert "不通过" in result.stdout


class TestArgumentValidation:
    def test_in_memory_requires_corpus(self):
        result = _run_cli(
            "--retriever",
            "in-memory",
            "--golden",
            str(FIXTURE_DIR / "golden.jsonl"),
        )
        assert result.returncode != 0
        assert "需要 --corpus" in (result.stdout + result.stderr)

    def test_qdrant_requires_collection(self):
        result = _run_cli(
            "--retriever",
            "qdrant",
            "--golden",
            str(FIXTURE_DIR / "golden.jsonl"),
        )
        assert result.returncode != 0
        assert "需要 --collection" in (result.stdout + result.stderr)

    def test_rerank_reports_unavailable_model(self):
        """精排模型不可用必须在**开始跑分前**就报错

        若等到跑完 100 条查询才发现，报告会显示「精排与基线无差异」，
        极易被误读为「精排没有增益」——而真实原因是模型根本没加载。

        这里指向一个不存在的本地目录，失败本身不依赖网络；但用例**必须**先
        ``import sentence_transformers``（进而 import ``transformers``）才能走到
        加载失败那一步，这一步在这台机器的沙箱下实测耗时约 90 秒（沙箱对每次
        ``open`` 走代理，而 ``transformers`` 导入期会扫描整个包目录）。因此该用例
        使用 :data:`HEAVY_TIMEOUT_SECONDS`，而不是默认的 120 秒——否则会把「环境慢」
        误报成「契约被破坏」。
        """
        result = _run_cli(
            "--retriever",
            "in-memory",
            "--golden",
            str(FIXTURE_DIR / "golden.jsonl"),
            "--corpus",
            str(FIXTURE_DIR / "corpus.jsonl"),
            "--rerank",
            "--rerank-model",
            "/nonexistent/reranker-model-for-test",
            timeout=HEAVY_TIMEOUT_SECONDS,
        )
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "精排模型不可用" in combined
        assert "reranker" in combined

    def test_index_dir_missing_manifest_reports_actionable_error(self, tmp_path):
        """--index-dir 指向空目录时应给出可操作提示，而不是 FileNotFoundError 栈"""
        result = _run_cli(
            "--retriever",
            "qdrant",
            "--index-dir",
            str(tmp_path),
        )
        assert result.returncode != 0
        assert "索引清单不可用" in (result.stdout + result.stderr)

    def test_invalid_k_rejected(self):
        result = _run_cli(
            "--retriever",
            "in-memory",
            "--golden",
            str(FIXTURE_DIR / "golden.jsonl"),
            "--corpus",
            str(FIXTURE_DIR / "corpus.jsonl"),
            "--k",
            "0,abc",
        )
        assert result.returncode != 0
        assert "--k" in (result.stdout + result.stderr)
