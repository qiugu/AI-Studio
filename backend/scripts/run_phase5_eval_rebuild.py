#!/usr/bin/env python
"""Phase 5 §4.4：评测语料重建 + dense / hybrid 双组对照（无人值守长任务编排）。

为什么需要这个编排入口
----------------------

本步骤在容器 CPU 上约 **8–10 小时**（52k 块 × 1.4 块/秒），必须能在与操作者终端
无关的进程里跑完。把三段命令串成一个「可重跑、可观察、失败即停」的入口，比让
运维记着「先跑哪个、再跑哪个、日志在哪」可靠得多。

三段（顺序不可颠倒）
--------------------

1. **建索引**：``index_rag_eval_corpus.py --hybrid``。**只建一次**即够两组对照——
   混合布局的集合上，纯稠密检索依然可用（``QdrantRetriever`` 走命名稠密向量），
   因此不需要为 dense 单独建一个集合。这也保证了「两组对照用的是同一份分块」。
2. **dense 对照**：同一集合上的纯稠密检索。
3. **hybrid 对照**：α=0.7 双路加权融合（实测 α∈{0.6,0.7,0.8} 均优于纯稠密）。

``--skip-index`` / ``--skip-eval`` 用于长任务中断后只补跑缺失的阶段：索引阶段按
``UPSERT_BATCH`` 批次落盘且同段落同序号 → 同 point id，重跑幂等。

如何避免「跑到一半被杀」
------------------------

**必须**以分离方式启动（``docker exec -d`` 或容器内 ``setsid nohup``）：实测把长任务
挂在一次 ``docker exec`` 的前台会话上，会话生命周期结束时进程会被一并回收，
表现为日志停在中途、无 traceback、无退出标记——比报错更难诊断。

日志与完成标记
--------------

每段日志追加写入 ``--log``（默认 ``data/rag_eval/v3_448_64/run.log``），
全部结束打印 ``PHASE5-EVAL-COMPLETE``。检查是否跑完，看这个标记即可。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SLUG = "rageval_t2r_v3"
DEFAULT_OUT_DIR = BACKEND_DIR / "data" / "rag_eval" / "v3_448_64"
DEFAULT_REPORT_DIR = BACKEND_DIR / "data" / "rag_eval" / "reports"
DEFAULT_DATA_DIR = BACKEND_DIR / "data" / "rag_eval"
#: 索引完成后打印的标记，供外部（人或自动化）判断长任务是否真的跑完
COMPLETION_MARKER = "PHASE5-EVAL-COMPLETE"


def build_stages(
    slug: str,
    out_dir: Path,
    report_dir: Path,
    data_dir: Path,
    *,
    alpha: float = 0.7,
    limit_passages: Optional[int] = None,
    skip_index: bool = False,
    skip_eval: bool = False,
) -> List[List[str]]:
    """构造要执行的命令序列（纯函数，便于断言「三段到底带了哪些参数」）"""
    collection = f"kb_{slug}"
    golden = str(data_dir / "golden.jsonl")
    stages: List[List[str]] = []

    if not skip_index:
        index_cmd = [
            sys.executable, "scripts/index_rag_eval_corpus.py",
            "--kb-slug", slug,
            "--hybrid",              # 一次写成混合布局，两组对照共用同一份分块
            "--recreate",            # 全量重索引必须显式重建，避免续写半成品
            "--data-dir", str(data_dir),
            "--out-dir", str(out_dir),
        ]
        if limit_passages is not None:
            index_cmd += ["--limit-passages", str(limit_passages)]
        stages.append(index_cmd)

    if not skip_eval:
        common = [
            sys.executable, "scripts/rag_eval.py",
            "--retriever", "qdrant",
            "--collection", collection,
            "--index-dir", str(out_dir),
            "--golden", golden,
            "--out-dir", str(report_dir),
        ]
        stages.append(common + ["--name", "v3-448-64-dense"])
        stages.append(
            common
            + ["--hybrid", "--hybrid-alpha", str(alpha)]
            + ["--name", f"v3-448-64-hybrid-a{alpha}"]
        )
    return stages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_phase5_eval_rebuild",
        description="评测语料重建 + dense/hybrid 对照（无人值守长任务，约 8–10 小时）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--slug", default=DEFAULT_SLUG, help="评测集合 slug（collection = kb_{slug}）")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="语料/金标目录")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="索引产物目录")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="评测报告目录")
    parser.add_argument("--alpha", type=float, default=0.7, help="混合检索稠密分支权重")
    parser.add_argument("--limit-passages", type=int, default=None,
                        help="只索引前 N 段（冒烟验证用，切勿用于正式对照）")
    parser.add_argument("--skip-index", action="store_true", help="索引已建好，只补跑评测")
    parser.add_argument("--skip-eval", action="store_true", help="只建索引，不跑评测")
    parser.add_argument("--log", default=None, help="日志路径（默认 <out-dir>/run.log）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的命令")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log) if args.log else out_dir / "run.log"

    stages = build_stages(
        args.slug, out_dir, Path(args.report_dir), Path(args.data_dir),
        alpha=args.alpha, limit_passages=args.limit_passages,
        skip_index=args.skip_index, skip_eval=args.skip_eval,
    )
    if not stages:
        raise SystemExit("没有要执行的阶段（--skip-index 与 --skip-eval 同时给出）")

    if args.dry_run:
        for index, cmd in enumerate(stages, start=1):
            print(f"[{index}/{len(stages)}] {' '.join(cmd)}")
        return 0

    started = time.perf_counter()
    with log_path.open("a", encoding="utf-8") as handle:
        for index, cmd in enumerate(stages, start=1):
            header = f"\n=== [{datetime.now():%F %T}] 阶段 {index}/{len(stages)}: {' '.join(cmd)} ===\n"
            print(header, flush=True)
            handle.write(header)
            handle.flush()
            # 子进程输出直写同一个文件句柄：既保留全部细节，也让日志顺序与阶段一致。
            # 失败即停（returncode 非 0 直接退出），避免「索引失败但评测照跑」——
            # 那会产出一份以残缺索引为依据、看起来却完全正常的报告。
            code = subprocess.call(cmd, stdout=handle, stderr=subprocess.STDOUT, cwd=str(BACKEND_DIR))
            if code != 0:
                message = f"\n阶段 {index} 失败，退出码 {code}；中止后续阶段。\n"
                handle.write(message)
                handle.flush()
                raise SystemExit(message.strip())

        elapsed = time.perf_counter() - started
        footer = (
            f"\n=== 全部 {len(stages)} 个阶段完成，用时 {elapsed/3600:.2f} h ===\n"
            f"{COMPLETION_MARKER}\n"
        )
        print(footer, flush=True)
        handle.write(footer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
