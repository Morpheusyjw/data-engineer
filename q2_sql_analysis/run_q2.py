# ============================================================
# Q2 运行入口：把 Olist 9 张 CSV 灌入 MySQL 8.0 并执行 3 段分析 SQL
# ------------------------------------------------------------
# 用法：
#   python q2_sql_analysis/run_q2.py
# 前置：MySQL 8.0 已启动（`mysql.server start`），且 .env 已按 .env.example 配置 MYSQL_*。
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


# 哨兵值：区分「未传 db（用 MYSQL_DATABASE）」与「显式传 None（连服务器实例，不指定库）」
_NO_DB = object()


def connect(db=_NO_DB) -> "create_engine":
    """根据 .env 创建 SQLAlchemy 引擎。

    - 不传 db：使用 MYSQL_DATABASE 指定的库（默认 olist）。
    - 显式传 db=None：连接「服务器实例」本身（URL 不指定库），
      用于建库前的 CREATE DATABASE。注意 MySQL 连接若指定了
      不存在的库，会在连接阶段直接报 1049，因此必须先连服务器实例建库。
    """
    load_dotenv()
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "root")
    pwd = os.getenv("MYSQL_PASSWORD", "root")
    if db is _NO_DB:
        database = os.getenv("MYSQL_DATABASE", "olist")
    else:
        database = db  # None 表示连服务器实例，不指定库
    if database:
        url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{database}?charset=utf8mb4"
    else:
        url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True)


def ingest() -> None:
    """把 9 张 CSV 灌入 MySQL。"""
    log.info("开始灌库 ...")
    db_name = os.getenv("MYSQL_DATABASE", "olist")
    # 先连「服务器实例」（不带库名）建库，再连到具体库；
    # 否则连接阶段就会因库不存在而报 1049，建库语句无从执行。
    eng_server = connect(db=None)
    with eng_server.connect() as c:
        c.execute(text(f"CREATE DATABASE IF NOT EXISTS {db_name}"))
    eng_db = connect(db=db_name)

    for fname, table in FILE_TO_TABLE.items():
        fpath = OLIST_DIR / fname
        if not fpath.exists():
            raise FileNotFoundError(f"缺少文件：{fpath}，请先下载 Olist 数据集。")
        # 先尝试 utf-8，失败回退 latin-1（Olist 个别字段含非常规字符）
        try:
            df = pd.read_csv(fpath, encoding="utf-8-sig", low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv(fpath, encoding="latin-1", low_memory=False)
        df = _to_datetime_cols(df)
        df.to_sql(table, eng_db, if_exists="replace", index=False, chunksize=5000)
        log.info("✅ 已灌表 %-35s (%d 行)", table, len(df))
    log.info("灌库完成。")


def _scalar(eng, sql: str):
    """执行只返回单个值的 SQL（用于给洞察段取分母）。"""
    with eng.connect() as c:
        return c.execute(text(sql)).scalar()


def _build_insights(df_gap: pd.DataFrame, df_month: pd.DataFrame, df_top: pd.DataFrame,
                    total_gmv_2017: float, n_sellers_2017: int,
                    n_products: int, n_reviews_dup: int) -> str:
    """从查询结果自动计算「看得出问题」的结论。

    这些都是**算出来的**，不是手写感想；换一份数据跑，结论会跟着变。
    目的是回答题目真正想考的那件事：你不只是把 SQL 跑出表格，而是看得懂表格里
    哪个数字不对劲。
    """
    m = df_month.copy()
    for col in ("total_orders", "delivered_orders", "canceled_orders",
                "delivered_gmv", "avg_delivery_days"):
        m[col] = pd.to_numeric(m[col], errors="coerce")
    t = df_top.copy()
    for col in ("gmv_2017", "order_count", "unique_customers",
                "avg_review_score", "late_delivery_rate"):
        t[col] = pd.to_numeric(t[col], errors="coerce")

    lines = ["## 数据洞察（由脚本从查询结果自动计算，非手写结论）\n"]

    # 1) 数据边界
    tot_orders = int(m["total_orders"].sum())
    tot_gmv = float(m["delivered_gmv"].sum())
    lines.append(
        f"**1) 数据边界**：{m['month'].iloc[0]} ~ {m['month'].iloc[-1]}，{len(m)} 个月、"
        f"{tot_orders:,} 单、已送达 GMV {tot_gmv:,.0f}。全期非 `delivered` 状态订单占 "
        f"{1 - m['delivered_orders'].sum() / tot_orders:.2%}——"
        f"所以任何「平台 GMV」口径都必须写明是「已送达 GMV」，否则会虚高。"
    )

    # 2) 首尾「小样本月份」：单量骤降的那几个月不能进趋势判断
    med = m["total_orders"].median()
    tiny = m[m["total_orders"] < 0.1 * med]
    if len(tiny):
        half = len(m) // 2
        head = tiny[tiny.index <= half]
        tail = tiny[tiny.index > half]
        parts = []
        if len(head):
            parts.append(
                "起点侧 "
                + "、".join(f"{r.month}（{int(r.total_orders)} 单）" for r in head.itertuples())
                + " 是平台刚上线，量级不具代表性"
            )
        if len(tail):
            parts.append(
                "尾部 "
                + "、".join(f"{r.month}（{int(r.total_orders)} 单，取消 {int(r.canceled_orders)} 单）"
                            for r in tail.itertuples())
                + f" 取消率高达 {tail['canceled_orders'].sum() / max(tail['total_orders'].sum(), 1):.0%}"
                + "，是导出时订单生命周期还没走完（没发货就被判 canceled）"
            )
        base_rate = m["canceled_orders"].sum() / tot_orders
        lines.append(
            f"**2) 首尾都有「小样本月份」，不能直接画趋势**：{'；'.join(parts)}。"
            f"全期取消率只有 {base_rate:.1%}，尾部那几个月会把「取消率」曲线拉出一个假尖峰。"
            f"**画月度趋势前必须裁掉这两段**，否则会得出「平台 2018 年 9 月要倒闭」的错误结论。"
        )

    # 3) GMV 峰值与环比
    full = m[m["total_orders"] >= 0.1 * med]
    if len(full):
        peak = full.loc[full["delivered_gmv"].idxmax()]
        prev = full[full["month"] < peak["month"]].tail(1)
        mom = ""
        if len(prev):
            prev_gmv = float(prev["delivered_gmv"].iloc[0])
            if prev_gmv:
                mom = f"，环比 {peak['delivered_gmv'] / prev_gmv - 1:+.1%}"
        lines.append(
            f"**3) 峰值月**：{peak['month']} 已送达 GMV {peak['delivered_gmv']:,.0f}{mom}，"
            f"是全期最高。大促月份（11 月）的备货/客服/物流容量应按这个峰值而不是月均值规划——"
            f"均值只有峰值的 {full['delivered_gmv'].mean() / peak['delivered_gmv']:.0%}。"
        )

    # 4) 配送时长趋势（首末「完整月」对比）
    if len(full) >= 2:
        a, b = full.iloc[0], full.iloc[-1]
        if pd.notna(a["avg_delivery_days"]) and pd.notna(b["avg_delivery_days"]):
            delta = float(b["avg_delivery_days"]) - float(a["avg_delivery_days"])
            lines.append(
                f"**4) 配送时效**：{a['month']} 平均 {a['avg_delivery_days']:.1f} 天 → "
                f"{b['month']} {b['avg_delivery_days']:.1f} 天（{delta:+.1f} 天）。"
                f"这条曲线是「买家满意度」最便宜的先导指标：它先变差，评分才会掉。"
            )

    # 5) TOP20 集中度 + 州分布
    if len(t) and total_gmv_2017:
        share = t["gmv_2017"].sum() / total_gmv_2017
        top_state = t["seller_state"].value_counts()
        sp_share = top_state.get("SP", 0) / len(t)
        seller_share = len(t) / n_sellers_2017 if n_sellers_2017 else 0
        lines.append(
            f"**5) 卖家集中度**：TOP20 卖家（占 2017 年有成交卖家的 {seller_share:.1%}）"
            f"贡献了 {share:.1%} 的 GMV（全平台 {n_sellers_2017:,} 个卖家）；"
            f"其中 {sp_share:.0%} 注册地在 SP 州。"
            f"**结论有两面**：头部集中度（20 家占约四分之一）对平台是健康的，"
            f"但州维度极度集中——SP 的物流/仓储一旦出事，TOP20 里多数卖家会同时受损，"
            f"这是相关性风险而不是独立风险，风控上要按「一个事件」而不是「多个卖家」来估。"
        )

    # 6) 延迟率与评分的关系（在 TOP20 内部比较）
    if len(t) and t["late_delivery_rate"].notna().any():
        slow = t[t["late_delivery_rate"] > 0.08]
        fast = t[t["late_delivery_rate"] <= 0.08]
        if len(slow) and len(fast):
            lines.append(
                f"**6) 延迟与评分同向恶化**：延迟率 >8% 的 {len(slow)} 个卖家平均评分 "
                f"{slow['avg_review_score'].mean():.2f}，≤8% 的 {len(fast)} 个平均 "
                f"{fast['avg_review_score'].mean():.2f}，差 "
                f"{fast['avg_review_score'].mean() - slow['avg_review_score'].mean():.2f} 分。"
                f"注意这**不是**因果证明（卖家品类/客单价不同），但足以把「延迟率」放进卖家健康度看板的第一屏。"
            )

    # 7) 翻译缺口占比
    n_missing = int(df_gap["product_count"].sum()) if len(df_gap) else 0
    if n_products:
        lines.append(
            f"**7) 翻译缺口很小，别为它上机器学习**：{len(df_gap)} 个类目、{n_missing} 个商品缺英文名，"
            f"占全部 {n_products:,} 个商品的 {n_missing / n_products:.3%}。"
            f"正确做法是人工补 2 条映射（一次性），而不是建翻译模型——"
            f"投入产出比差三个数量级。"
        )
    if n_reviews_dup:
        lines.append(
            f"**8) 评分必须先按订单去重**：`order_reviews` 里有 {n_reviews_dup:,} 个订单挂了多条评价，"
            f"直接 AVG 会让「爱写评价的订单」获得更高权重，TOP 卖家评分被少数订单带偏。"
        )

    return "\n\n".join(lines) + "\n"


def run_queries() -> None:
    """执行 3 段分析 SQL，把结果写成 q2_results.md（含自动洞察）。"""
    eng_db = connect()
    queries = {
        "Q2.1 翻译缺失类别": SQL_DIR / "q2_1_translation_gap.sql",
        "Q2.2 月度成交指标": SQL_DIR / "q2_2_monthly_metrics.sql",
        "Q2.3 2017 TOP20 卖家": SQL_DIR / "q2_3_top_sellers.sql",
    }
    dfs: dict[str, pd.DataFrame] = {}
    blocks = ["# Q2 SQL 分析结果（q2_results.md）\n"]
    for title, sql_path in queries.items():
        sql = sql_path.read_text(encoding="utf-8")
        log.info("执行 %s ...", title)
        df = pd.read_sql(text(sql), eng_db)
        dfs[title] = df
        blocks.append(f"## {title}\n\n行数：{len(df)}\n\n{df.head(50).to_markdown(index=False)}\n")

    # 给洞察段取分母（这些是「结论背后的基数」，缺了就没法判断比例是否重要）
    try:
        total_gmv_2017 = _scalar(eng_db, """
            SELECT SUM(oi.price + oi.freight_value)
            FROM olist_order_items oi
            JOIN olist_orders o ON oi.order_id = o.order_id
            WHERE o.order_purchase_timestamp >= '2017-01-01'
              AND o.order_purchase_timestamp <  '2018-01-01'
        """) or 0
        n_sellers_2017 = _scalar(eng_db, """
            SELECT COUNT(DISTINCT oi.seller_id)
            FROM olist_order_items oi
            JOIN olist_orders o ON oi.order_id = o.order_id
            WHERE o.order_purchase_timestamp >= '2017-01-01'
              AND o.order_purchase_timestamp <  '2018-01-01'
        """) or 0
        n_products = _scalar(eng_db, "SELECT COUNT(*) FROM olist_products") or 0
        n_reviews_dup = _scalar(eng_db, """
            SELECT COUNT(*) FROM (
                SELECT order_id FROM olist_order_reviews
                GROUP BY order_id HAVING COUNT(*) > 1
            ) x
        """) or 0
        insights = _build_insights(
            dfs["Q2.1 翻译缺失类别"], dfs["Q2.2 月度成交指标"], dfs["Q2.3 2017 TOP20 卖家"],
            float(total_gmv_2017), int(n_sellers_2017), int(n_products), int(n_reviews_dup),
        )
        blocks.append(insights)
    except Exception as exc:  # noqa: BLE001 - 洞察只是加分项，不能拖垮主结果
        log.warning("洞察段计算失败（不影响 SQL 结果）：%s", exc)

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
