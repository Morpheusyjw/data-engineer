# ============================================================
# 数据集下载脚本
# ------------------------------------------------------------
# 作用：把笔试用到的两份 Kaggle 数据集下载到本地 data/ 目录，
#       使 `python run_all.py` 能从 0 到 1 跑通（含数据下载）。
#
# 设计要点：
#   1. 幂等：文件已存在则跳过，避免重复下载。
#   2. 自动优先：优先用 kagglehub 自动下载（需要 Kaggle 账号凭证）。
#   3. 优雅降级：若没有 Kaggle 凭证导致自动下载失败，
#      打印清晰的"手动下载步骤"后抛出可读异常，
#      由 run_all.py 捕获并记录，不阻塞其他模块。
#   4. 文件名归一化：Kaggle 原始文件名大小写不一致
#      （online_retail_II.csv vs online_retail_ii.csv），这里统一重命名，
#      避免大小写敏感文件系统（Linux/macOS）上路径对不上。
# ============================================================

from __future__ import annotations

import os
import shutil
import sys
import logging
from pathlib import Path

# 项目根目录：本文件位于 <root>/download_data.py
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
OLIST_DIR = DATA_DIR / "olist"

# Kaggle 数据集标识（owner/dataset）
ONLINE_RETAIL_KAGGLE = "mashlyn/online-retail-ii-uci"
OLIST_KAGGLE = "olistbr/brazilianecommerce"

# 期望的最终落地文件名（题目代码引用的路径）
ONLINE_RETAIL_TARGET = DATA_DIR / "online_retail_ii.csv"
OLIST_TARGET_FILES = [
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("download_data")


def _ensure_dirs() -> None:
    """确保 data/ 与 data/olist/ 目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OLIST_DIR.mkdir(parents=True, exist_ok=True)


def _find_file_case_insensitive(directory: Path, filename: str) -> Path | None:
    """在 directory 中按大小写不敏感方式查找 filename，返回首个匹配路径。"""
    target_lower = filename.lower()
    for p in directory.rglob("*"):
        if p.is_file() and p.name.lower() == target_lower:
            return p
    return None


def _try_copy_online_retail_from(src_dir: Path) -> bool:
    """从 kagglehub 下载目录里找到 online retail 文件并归一化复制到 data/。"""
    if ONLINE_RETAIL_TARGET.exists():
        log.info("Online Retail II 已存在，跳过：%s", ONLINE_RETAIL_TARGET)
        return True
    # Kaggle 原始文件名可能为 online_retail_II.csv（大写 II）
    src = _find_file_case_insensitive(src_dir, "online_retail_II.csv")
    if src is None:
        return False
    shutil.copyfile(src, ONLINE_RETAIL_TARGET)
    log.info("已复制并重命名：%s -> %s", src.name, ONLINE_RETAIL_TARGET)
    return True


def _try_copy_olist_from(src_dir: Path) -> bool:
    """从 kagglehub 下载目录把 9 个 Olist CSV 复制到 data/olist/。"""
    missing = []
    for fname in OLIST_TARGET_FILES:
        dst = OLIST_DIR / fname
        if dst.exists():
            continue
        src = _find_file_case_insensitive(src_dir, fname)
        if src is None:
            missing.append(fname)
            continue
        shutil.copyfile(src, dst)
        log.info("已复制：%s -> %s", src.name, dst)
    if missing:
        log.warning("Olist 还有 %d 个文件未找到：%s", len(missing), missing)
        return False
    return True


def _print_manual_guide() -> None:
    """打印手动下载步骤（当自动下载不可用时的兜底指引）。"""
    guide = """
==================================================================
自动下载失败（通常是没有配置 Kaggle 凭证）。请手动下载数据：
------------------------------------------------------------------
步骤 1：注册并配置 Kaggle 凭证
  1) 打开 https://www.kaggle.com 注册/登录账号
  2) 进入 Account -> API -> 点击 "Create New Token"
     会下载 kaggle.json（含 username 和 key）
  3) 把 kaggle.json 放到以下位置之一：
       macOS/Linux: ~/.kaggle/kaggle.json
       Windows:     C:\\Users\\<你>\\.kaggle\\kaggle.json
  4) 修改权限（macOS/Linux）：
       chmod 600 ~/.kaggle/kaggle.json

步骤 2：手动下载两份数据集并放到对应目录
  A) Online Retail II
     地址: https://www.kaggle.com/datasets/mashlyn/online-retail-ii-uci
     下载后把文件重命名为 online_retail_ii.csv，放到 data/ 目录
  B) Brazilian E-Commerce by Olist
     地址: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
     解压后把 9 个 olist_*.csv 放到 data/olist/ 目录

步骤 3：放置完成后重新运行 `python run_all.py`
==================================================================
"""
    print(guide)


def download_online_retail() -> bool:
    """下载 Online Retail II。成功返回 True，失败（需手动）返回 False。"""
    if ONLINE_RETAIL_TARGET.exists():
        log.info("Online Retail II 已存在，跳过下载。")
        return True
    try:
        import kagglehub

        log.info("尝试用 kagglehub 下载 Online Retail II ...")
        # 返回的是下载目录的本地路径
        path = kagglehub.dataset_download(ONLINE_RETAIL_KAGGLE)
        return _try_copy_online_retail_from(Path(path))
    except Exception as exc:  # noqa: BLE001 - 任何下载异常都转为可读提示
        log.warning("Online Retail II 自动下载失败：%s", exc)
        return False


def download_olist() -> bool:
    """下载 Olist 9 张表。成功返回 True，失败（需手动）返回 False。"""
    needed = [OLIST_DIR / f for f in OLIST_TARGET_FILES]
    if all(p.exists() for p in needed):
        log.info("Olist 9 张表已存在，跳过下载。")
        return True
    try:
        import kagglehub

        log.info("尝试用 kagglehub 下载 Olist ...")
        path = kagglehub.dataset_download(OLIST_KAGGLE)
        return _try_copy_olist_from(Path(path))
    except Exception as exc:  # noqa: BLE001
        log.warning("Olist 自动下载失败：%s", exc)
        return False


def main() -> int:
    """入口：下载两份数据集；若自动失败则打印手动指引并退出码 1。"""
    _ensure_dirs()
    ok_retail = download_online_retail()
    ok_olist = download_olist()

    if ok_retail and ok_olist:
        log.info("✅ 两份数据集均已就绪。")
        return 0

    _print_manual_guide()
    log.error("❌ 数据集未完全就绪，请按上方指引手动处理后重试。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
