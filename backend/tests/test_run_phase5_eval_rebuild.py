"""Phase 5 评测编排脚本单测（``scripts/run_phase5_eval_rebuild.py``）

编排脚本的价值全在「命令到底带了哪些参数」与「失败是否即停」两点上：
少一个 ``--hybrid`` 会产出一份标签写着 hybrid、数据其实是 dense-only 的报告；
索引失败却继续跑评测会产出以残缺索引为依据、看起来却完全正常的结论。
故此处针对性覆盖这两类。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "run_phase5_eval_rebuild.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_phase5_eval_rebuild_test", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_script_module()


def _stages(tmp_path, **kwargs):
    return runner.build_stages(
        "rageval_t2r_v3",
        tmp_path / "out",
        tmp_path / "reports",
        tmp_path / "data",
        **kwargs,
    )


class TestStageConstruction:
    def test_three_stages_in_order(self, tmp_path):
        """索引 → dense → hybrid：顺序不可颠倒（对照要先有索引）"""
        stages = _stages(tmp_path)

        assert len(stages) == 3
        assert "index_rag_eval_corpus.py" in " ".join(stages[0])
        assert "rag_eval.py" in " ".join(stages[1])
        assert "rag_eval.py" in " ".join(stages[2])

    def test_index_stage_is_hybrid_recreate_with_separate_out_dir(self, tmp_path):
        stages = _stages(tmp_path)
        index = stages[0]

        assert "--hybrid" in index
        assert "--recreate" in index
        # 独立产物目录：稠密/混合两次运行不得互相覆盖
        assert index[index.index("--out-dir") + 1] == str(tmp_path / "out")

    def test_dense_arm_has_no_hybrid_flag(self, tmp_path):
        """稠密对照臂绝不能带 --hybrid，否则两组对照变成同一组"""
        dense = _stages(tmp_path)[1]

        assert "--hybrid" not in dense
        assert "--index-dir" in dense and "--golden" in dense

    def test_hybrid_arm_carries_alpha(self, tmp_path):
        hybrid = _stages(tmp_path, alpha=0.8)[2]

        assert "--hybrid" in hybrid
        assert hybrid[hybrid.index("--hybrid-alpha") + 1] == "0.8"

    def test_both_arms_share_same_collection_and_index_dir(self, tmp_path):
        """两组必须指向同一集合与同一索引目录——否则对照组之间不可比"""
        _, dense, hybrid = _stages(tmp_path)

        def _value(cmd, flag):
            return cmd[cmd.index(flag) + 1]

        for flag in ("--collection", "--index-dir", "--golden"):
            assert _value(dense, flag) == _value(hybrid, flag)

    def test_limit_passages_only_affects_index_stage(self, tmp_path):
        stages = _stages(tmp_path, limit_passages=100)

        assert stages[0][stages[0].index("--limit-passages") + 1] == "100"
        assert "--limit-passages" not in stages[1]

    def test_skip_flags_remove_whole_stages(self, tmp_path):
        assert len(_stages(tmp_path, skip_index=True)) == 2
        assert len(_stages(tmp_path, skip_eval=True)) == 1


class TestExecution:
    def test_dry_run_does_not_execute(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(runner.subprocess, "call",
                            lambda *a, **k: pytest.fail("dry-run 不应执行命令"))

        code = runner.main([
            "--out-dir", str(tmp_path / "out"),
            "--report-dir", str(tmp_path / "reports"),
            "--data-dir", str(tmp_path / "data"),
            "--dry-run",
        ])

        assert code == 0
        assert "index_rag_eval_corpus.py" in capsys.readouterr().out

    def test_failure_stops_subsequent_stages(self, tmp_path, monkeypatch):
        """索引失败必须中止：否则会产出以残缺索引为依据的「正常」报告"""
        calls = []

        def fake_call(cmd, **kwargs):
            calls.append(cmd)
            return 1  # 第一段即失败

        monkeypatch.setattr(runner.subprocess, "call", fake_call)

        with pytest.raises(SystemExit, match="阶段 1 失败"):
            runner.main([
                "--out-dir", str(tmp_path / "out"),
                "--report-dir", str(tmp_path / "reports"),
                "--data-dir", str(tmp_path / "data"),
            ])

        assert len(calls) == 1  # 只跑了第一段

    def test_success_writes_completion_marker(self, tmp_path, monkeypatch):
        """完成标记是外部判断「长任务真的跑完」的唯一依据"""
        monkeypatch.setattr(runner.subprocess, "call", lambda cmd, **kwargs: 0)
        log_path = tmp_path / "run.log"

        code = runner.main([
            "--out-dir", str(tmp_path / "out"),
            "--report-dir", str(tmp_path / "reports"),
            "--data-dir", str(tmp_path / "data"),
            "--log", str(log_path),
        ])

        assert code == 0
        assert runner.COMPLETION_MARKER in log_path.read_text(encoding="utf-8")

    def test_no_stage_selected_is_an_error(self, tmp_path):
        with pytest.raises(SystemExit, match="没有要执行的阶段"):
            runner.main([
                "--out-dir", str(tmp_path / "out"),
                "--data-dir", str(tmp_path / "data"),
                "--skip-index", "--skip-eval",
            ])
