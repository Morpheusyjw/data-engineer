# ============================================================
# 环境自检脚本（check_env.py）
# ------------------------------------------------------------
# 给小白用的「体检」工具：一键打印本机是否满足笔试运行要求。
# 用法：python check_env.py
# 绿色 ✅ = 已就绪；红色 ❌ = 还需配置（对照 SETUP.md 处理）。
# ============================================================

from __future__ import annotations

import shutil
import subprocess
import sys


def _ver(cmd: list[str]) -> str | None:
    """执行命令并返回版本字符串；找不到返回 None。"""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if out.returncode == 0:
            return out.stdout.strip().splitlines()[0]
    except Exception:
        return None
    return None


def _check(name: str, ok: bool, detail: str = "") -> None:
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f"  —— {detail}" if detail else ""))


def main() -> None:
    print("========== 数据工程师笔试 · 环境自检 ==========\n")

    # 1) Python
    py = _ver([sys.executable, "--version"]) or _ver(["python3", "--version"])
    print("[1] Python")
    if py:
        major, minor = sys.version_info[:2]
        _check(f"Python 版本 ({py})", major == 3 and minor >= 10,
               "需要 3.10+，当前满足" if (major == 3 and minor >= 10) else "需要升级到 3.10+")
    else:
        _check("Python 已安装", False, "未检测到")

    # 2) 包管理器 / 工具
    print("\n[2] 基础工具")
    _check("Homebrew (brew)", shutil.which("brew") is not None,
           "macOS 包管理器，SETUP.md 第 1 步")
    _check("Git", shutil.which("git") is not None, "代码提交必备")
    _check("Docker", shutil.which("docker") is not None,
           "跑 MySQL 8.0 最省事的方式（SETUP.md 第 6 步）")

    # 3) Kaggle 凭证
    print("\n[3] 数据集下载凭证 (Kaggle)")
    import os
    kaggle_paths = [
        os.path.expanduser("~/.kaggle/kaggle.json"),
        os.path.join(os.getcwd(), "kaggle.json"),
    ]
    has_kaggle = any(os.path.exists(p) for p in kaggle_paths)
    _check("Kaggle token (kaggle.json)", has_kaggle,
           "没有则按 SETUP.md 第 5 步注册并生成")

    # 4) 数据是否已下载
    print("\n[4] 数据集文件")
    from pathlib import Path
    root = Path(__file__).resolve().parent
    retail = (root / "data" / "online_retail_ii.csv").exists()
    olist_ok = all((root / "data" / "olist" / f).exists()
                   for f in ["olist_orders_dataset.csv", "olist_order_items_dataset.csv"])
    _check("Online Retail II (data/online_retail_ii.csv)", retail)
    _check("Olist 9 张表 (data/olist/*.csv)", olist_ok)

    # 5) MySQL 连通性（可选：没装 Docker 这里会显示未连接，属正常）
    print("\n[5] MySQL 8.0（Q2 用，可稍后配置）")
    try:
        import sqlalchemy
        url = "mysql+pymysql://root:root@127.0.0.1:3306/"
        eng = sqlalchemy.create_engine(url, pool_pre_ping=True)
        with eng.connect() as c:
            c.execute(sqlalchemy.text("SELECT VERSION()"))
        _check("本地 MySQL 可连接 (root/root@3306)", True)
    except Exception:
        _check("本地 MySQL 可连接", False,
               "尚未启动；按 SETUP.md 第 6 步起 MySQL 后会变绿")

    # 6) LLM Key（可选：Q4 用，没有也能跑规则兜底）
    print("\n[6] LLM API Key（Q4 用，可选）")
    has_key = bool(os.environ.get("OPENAI_API_KEY")) or (root / ".env").exists()
    _check("OpenAI Key 已配置", has_key,
           "没有则 Q4 走规则兜底；按 SETUP.md 第 7 步申请可解锁完整大模型版")

    print("\n========== 自检结束 ==========")
    print("提示：❌ 项请对照 SETUP.md 对应步骤处理；✅ 项即可放心使用。")


if __name__ == "__main__":
    main()
