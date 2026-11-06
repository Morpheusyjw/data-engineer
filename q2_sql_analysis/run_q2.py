# ============================================================
# Q2 运行入口：把 Olist 9 张 CSV 灌入 MySQL 8.0 并执行 3 段分析 SQL
# ------------------------------------------------------------
# 用法：
#   python q2_sql_analysis/run_q2.py
# 前置：MySQL 8.0 已启动（见 SETUP.md 第 6 步），且 .env 已配置 MYSQL_*。
# 若连不上 MySQL，会抛出清晰异常，由 run_all.py 捕获并记录（不阻塞其他模块）。
# ============================================================

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("Q2")

ROOT = Path(__file__).resolve().parents[1]
OLIST_DIR = ROOT / "data" / "olist"
SQL_DIR = Path(__file__).resolve().parent
RESULT_MD = SQL_DIR / "q2_results.md"

# 需要灌库的 9 个文件 -> 目标表名（去掉 _dataset 后缀，与 .sql 中引用一致）
FILE_TO_TABLE = {
    "olist_customers_dataset.csv": "olist_customers",
    "olist_geolocation_dataset.csv": "olist_geolocation",
    "olist_order_items_dataset.csv": "olist_order_items",
    "olist_order_payments_dataset.csv": "olist_order_payments",
    "olist_order_reviews_dataset.csv": "olist_order_reviews",
    "olist_orders_dataset.csv": "olist_orders",
    "olist_products_dataset.csv": "olist_products",
    "olist_sellers_dataset.csv": "olist_sellers",
    "product_category_name_translation.csv": "product_category_name_translation",
}

# 这些列名包含时间，灌库前转成 datetime，保证 SQL 中 DATE_FORMAT/DATEDIFF 可用
TIME_COL_HINTS = ("timestamp", "_date", "_at")


def _to_datetime_cols(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        low = col.lower()
        if any(h in low for h in TIME_COL_HINTS):
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def connect(db: str | None = None) -> "create_engine":
    """根据 .env 创建 SQLAlchemy 引擎。"""
    load_dotenv()
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "root")
    pwd = os.getenv("MYSQL_PASSWORD", "root")
    database = db or os.getenv("MYSQL_DATABASE", "olist")
    url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{database}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True)


def ingest() -> None:
    """把 9 张 CSV 灌入 MySQL。"""
    log.info("开始灌库 ...")
    engine = connect()
    # 确保数据库存在
    with engine.connect() as c:
        c.execute(text(f"CREATE DATABASE IF NOT EXISTS {os.getenv('MYSQL_DATABASE', 'olist')}"))
    eng_db = connect()  # 重连到具体库
    eng_db = create_engine(  # noqa
        f"mysql+pymysql://{os.getenv('MYSQL_USER','root')}:{os.getenv('MYSQL_PASSWORD','root')}"
        f"@{os.getenv('MYSQL_HOST','127.0.0.1')}:{int(os.getenv('MYSQL_PORT','3306'))}"
        f"/{os.getenv('MYSQL_DATABASE','olist')}?charset=utf8mb4",
        pool_pre_ping=True,
    )

    for fname, table in FILE_TO_TABLE.items():
        fpath = OLIST_DIR / fname
        if not fpath.exists():
            raise FileNotFoundError(f"缺少文件：{fpath}，请先下载 Olist 数据集。")
        # 先尝试 utf-8，失败回退 latin-1（Olist 个别字段含非常规字符）
        try:
            df = pd.read_csv(fpath, encoding="utf-8", low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv(fpath, encoding="latin-1", low_memory=False)
        df = _to_datetime_cols(df)
        df.to_sql(table, eng_db, if_exists="replace", index=False, chunksize=5000)
        log.info("✅ 已灌表 %-35s (%d 行)", table, len(df))
    log.info("灌库完成。")


def run_queries() -> None:
    """执行 3 段分析 SQL，把结果写成 q2_results.md。"""
    eng_db = connect()
    queries = {
        "Q2.1 翻译缺失类别": SQL_DIR / "q2_1_translation_gap.sql",
        "Q2.2 月度成交指标": SQL_DIR / "q2_2_monthly_metrics.sql",
        "Q2.3 2017 TOP20 卖家": SQL_DIR / "q2_3_top_sellers.sql",
    }
    blocks = ["# Q2 SQL 分析结果（q2_results.md）\n"]
    for title, sql_path in queries.items():
        sql = sql_path.read_text(encoding="utf-8")
        log.info("执行 %s ...", title)
        df = pd.read_sql(text(sql), eng_db)
        blocks.append(f"## {title}\n\n行数：{len(df)}\n\n{df.head(50).to_markdown(index=False)}\n")
    RESULT_MD.write_text("\n".join(blocks), encoding="utf-8")
    log.info("✅ 结果已写入 %s", RESULT_MD)


def run() -> int:
    log.info("===== Q2 SQL 分析 开始 =====")
    ingest()
    run_queries()
    log.info("===== Q2 完成 =====")
    return 0


if __name__ == "__main__":
    sys.exit(run())
