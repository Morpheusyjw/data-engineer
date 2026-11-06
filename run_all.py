# ============================================================
# 一键运行入口（run_all.py）
# ------------------------------------------------------------
# 作用：从 0 到 1 跑通整条 pipeline，包括「数据下载 → 各模块依次执行」。
#
# 关键设计（满足题目要求）：
#   1. 先下载数据（download_data），失败不致命，仅记录并继续。
#   2. 每个模块用 try/except 隔离：某一个模块报错不会拖垮后面，
#      满足"不要因为模块 1 报错导致后面全跑不了"。
#   3. 每个模块也可独立运行（例如 `python q3_etl_pipeline/pipeline.py`）。
#   4. 最后打印执行摘要，方便定位哪些模块没跑通、为什么。
#
# 用法：
#   python run_all.py            # 跑全部
#   python run_all.py --only q1 # 只跑 Q1（调试用）
# ============================================================

from __future__ import annotations

import argparse
import importlib
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import download_data  # 数据下载模块（同目录）

# 模块注册表：(名称, 导入路径, 入口函数)
# 顺序即执行顺序；每个模块必须提供 run() -> int（0 表示成功）
MODULES = [
    ("Q1 数据质量探索", "q1_data_quality.q1_code", "run"),
    ("Q2 SQL 分析与 MySQL 灌库", "q2_sql_analysis.run_q2", "run"),
    ("Q3 ETL 管道", "q3_etl_pipeline.pipeline", "run"),
    ("Q4 LLM 评价抽取", "q4_llm_extraction.extract_reviews", "run"),
    ("Q5 系统设计（文档，无需运行）", "q5_system_design.check", "run"),
    ("Bonus 加分题（文档，无需运行）", "bonus.check", "run"),
]


def _banner(msg: str) -> None:
    print("\n" + "=" * 64)
    print(msg)
    print("=" * 64)


def run_module(name: str, import_path: str, func_name: str) -> tuple[bool, str]:
    """运行单个模块，返回 (是否成功, 备注)。任何异常都被捕获。"""
    try:
        mod = importlib.import_module(import_path)
        func = getattr(mod, func_name)
        _banner(f"▶ 开始执行：{name}")
        t0 = time.time()
        rc = func()  # 期望返回 0/None 表示成功
        elapsed = time.time() - t0
        ok = rc in (0, None)
        note = f"用时 {elapsed:.1f}s" if ok else f"返回码={rc}"
        return ok, note
    except Exception as exc:  # noqa: BLE001 - 隔离异常，保证后续模块继续
        _banner(f"✗ {name} 执行失败")
        print(f"错误类型：{type(exc).__name__}")
        print(f"错误信息：{exc}")
        print("—— 该模块跳过，不影响其他模块 ——")
        # 打印精简堆栈，便于定位（不阻塞流程）
        tb = traceback.format_exc(limit=3)
        print(tb)
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="数据工程师笔试题 一键运行")
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="只运行指定模块，例如 --only q1 q3（不区分大小写）",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="跳过数据下载（数据已存在时使用）",
    )
    args = parser.parse_args()

    _banner("数据工程师笔试题 · 一键运行")
    print(f"项目根目录：{PROJECT_ROOT}")

    # 1) 数据下载（非致命）
    if not args.skip_download:
        _banner("步骤 1 / 数据下载")
        try:
            rc = download_data.main()
            if rc != 0:
                print("⚠️ 数据自动下载未成功，请参照上方指引手动下载后重跑。")
                print("   后续依赖数据的模块会自行报告缺失并跳过。")
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 下载阶段异常：{exc}")

    # 2) 依次运行各模块
    selected = {m.lower() for m in (args.only or [])}
    results: dict[str, tuple[bool, str]] = {}

    for name, path, func in MODULES:
        # 支持用 "q1" / "q2" 这样的短名过滤
        short = name.split()[0].lower()
        if selected and short not in selected and name.lower() not in selected:
            print(f"· 跳过（未被 --only 选中）：{name}")
            continue
        ok, note = run_module(name, path, func)
        results[name] = (ok, note)

    # 3) 摘要
    _banner("执行摘要")
    all_ok = True
    for name, (ok, note) in results.items():
        status = "✅ 成功" if ok else "❌ 失败"
        print(f"  {status}  {name}  — {note}")
        all_ok = all_ok and ok

    print()
    if all_ok:
        print("🎉 全部模块执行成功！")
    else:
        print("⚠️ 有模块未跑通（见上方摘要）。常见原因与对策：")
        print("   - 缺数据 → 配置 Kaggle 凭证或手动下载（见 download_data 指引）")
        print("   - Q2 连不上 MySQL → 确认 MySQL 8.0 已启动且账号密码正确")
        print("   - Q4 没 Key → 已自动降级为规则方法，仍可产出结果")
    return 0


if __name__ == "__main__":
    sys.exit(main())
