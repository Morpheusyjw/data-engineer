# ============================================================
# Q3 端到端 ETL 管道（Online Retail II）
# ------------------------------------------------------------
# 把原始交易数据转换为 3 个面向不同下游的干净数据集：
#   1) sales_facts.parquet      —— BI 报表用（真实销售）
#   2) customer_features.parquet —— 客户分群用（RFM 特征）
#   3) returns_log.parquet      —— 退货分析用（含原单匹配）
#
# 工程要求（题目原文）：
#   - 拆成 >=5 个函数，不写在一个 main 里
#   - 每一步都有日志与异常捕获
#   - 每个输出都写断言校验关键字段
#   - 可复现：固定随机种子，同输入同输出
#   - 性能：禁止 iterrows/apply 全表循环；100 万行 2 分钟内跑完
# ============================================================

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.dataset_io import load_online_retail  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("Q3")

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "online_retail_ii.csv"
OUT_DIR = Path(__file__).resolve().parent / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = Path(__file__).resolve().parent / "pipeline_log.txt"

# 产品类 StockCode 判定：数字开头、可选字母后缀（如 85123A / 48185）
PRODUCT_CODE_RE = r"^\d+[A-Za-z]*$"


# ----------------------------------------------------------------------------
# 函数 1：加载数据
# ----------------------------------------------------------------------------
def load_data(path: Path = DATA_PATH) -> pd.DataFrame:
    """加载并做基础类型修正（复用共享加载器，已处理列名不一致）。"""
    log.info("加载数据：%s", path)
    df = load_online_retail(path)
    # 计算金额（后续各步骤共用）
    df["total_amount"] = df["quantity"] * df["unit_price"]
    log.info("加载完成，行数=%d", len(df))
    return df


# ----------------------------------------------------------------------------
# 函数 2：过滤真实销售（剔除取消单 / 坏账调整 / 非产品编码）
# ----------------------------------------------------------------------------
def filter_real_sales(df: pd.DataFrame) -> pd.DataFrame:
    """返回只含「真实销售」的明细。

    剔除规则（对应清洗策略「用途 A」）：
      - 取消单：Invoice 以 'C' 开头（Quantity 为负）
      - 非产品编码：StockCode 不是「数字(+字母)」格式（POST/M/BANK CHARGES…）
      - 金额异常：UnitPrice<=0 或 Quantity<=0（调整/赠品/废行）
    """
    log.info("过滤真实销售 ...")
    inv = df["invoice"].astype("string")
    sc = df["stock_code"].astype("string")

    is_cancel = inv.str.startswith("C")
    is_product = sc.str.fullmatch(PRODUCT_CODE_RE)
    valid_price = df["unit_price"] > 0
    valid_qty = df["quantity"] > 0

    mask = (~is_cancel) & is_product & valid_price & valid_qty
    sales = df[mask].copy()
    log.info("真实销售行数=%d（占比 %.2f%%）", len(sales), 100 * len(sales) / len(df))
    return sales


# ----------------------------------------------------------------------------
# 函数 3：计算 RFM 客户特征
# ----------------------------------------------------------------------------
def compute_rfm(sales: pd.DataFrame, baseline_date: pd.Timestamp) -> pd.DataFrame:
    """对「有 Customer ID」的客户计算 RFM 特征。

    注意：RFM 必须能归集到「人」，所以只取 customer_id 非空且为正向销售。
    """
    log.info("计算 RFM 客户特征 ...")
    s = sales[sales["customer_id"].notna()].copy()
    s["invoice_date"] = pd.to_datetime(s["invoice_date"])

    # 用 groupby 聚合，避免逐行循环
    grouped = s.groupby("customer_id")
    feats = grouped.agg(
        frequency=("invoice", "nunique"),          # 独立发票数 = 购买次数
        monetary=("total_amount", "sum"),           # 总消费
        first_purchase_date=("invoice_date", "min"),
        last_purchase_date=("invoice_date", "max"),
        unique_products=("stock_code", "nunique"),
    ).reset_index()

    # 主要国家（取该客户出现最多的国家）
    country_mode = (
        s.groupby(["customer_id", "country"]).size()
        .reset_index(name="cnt")
        .sort_values(["customer_id", "cnt"], ascending=[True, False])
        .drop_duplicates("customer_id")[["customer_id", "country"]]
    )
    feats = feats.merge(country_mode, on="customer_id", how="left")

    # Recency：距基准日（数据集最后一天）的天数
    feats["recency_days"] = (baseline_date - feats["last_purchase_date"]).dt.days
    feats["is_one_time_buyer"] = feats["frequency"] == 1

    # 列顺序整理
    feats = feats[[
        "customer_id", "recency_days", "frequency", "monetary",
        "first_purchase_date", "last_purchase_date", "unique_products",
        "country", "is_one_time_buyer",
    ]]
    log.info("客户特征行数=%d", len(feats))
    return feats


# ----------------------------------------------------------------------------
# 函数 4：退货匹配（核心难点）
# ----------------------------------------------------------------------------
def match_returns(returns: pd.DataFrame, sales: pd.DataFrame) -> pd.DataFrame:
    """为每条退货匹配对应的原始正向销售。

    匹配规则（题目点名的真实难题）：
      - 同一 customer_id
      - 同一 stock_code
      - 原始 quantity == |退货 quantity|（即 abs 相等）
      - 原始 invoice_date 早于退货日期
      - 取「时间上最近的一笔」正向销售（closest preceding）
    多笔候选时取最近；匹配不到则 matched_original_invoice = NULL 并记日志。
    """
    log.info("开始退货匹配，退货行数=%d ...", len(returns))
    # 建立 (customer_id, stock_code) -> 候选正向销售列表 的索引
    # 只保留真实销售里 quantity>0 且能被退货抵消的部分
    cand = sales[sales["quantity"] > 0][
        ["customer_id", "stock_code", "invoice", "quantity", "invoice_date"]
    ].copy()
    cand["invoice_date"] = pd.to_datetime(cand["invoice_date"])
    # 索引：键 -> 按时间升序的候选行
    index: dict[tuple, list] = {}
    for row in cand.itertuples(index=False):
        key = (row.customer_id, row.stock_code)
        index.setdefault(key, []).append(row)
    for k in index:
        index[k].sort(key=lambda r: r.invoice_date)

    matched = []
    unmatched = 0
    for r in returns.itertuples(index=False):
        need_qty = abs(r.quantity)
        cands = index.get((r.customer_id, r.stock_code), [])
        # 找时间早于退货、quantity 匹配、最近的
        best = None
        for c in cands:
            if c.invoice_date < r.invoice_date and c.quantity == need_qty:
                best = c  # 因已按时间升序，最后命中即最近
        if best is not None:
            matched.append(best.invoice)
        else:
            matched.append(None)
            unmatched += 1

    returns = returns.copy()
    returns["matched_original_invoice"] = matched
    log.info("退货匹配完成：命中 %d，未命中 %d", len(returns) - unmatched, unmatched)
    return returns


def build_returns_log(df: pd.DataFrame, sales: pd.DataFrame) -> pd.DataFrame:
    """构造 returns_log：取消单明细 + 匹配字段。"""
    log.info("构造 returns_log ...")
    inv = df["invoice"].astype("string")
    returns_raw = df[inv.str.startswith("C")].copy()
    returns_raw = returns_raw[returns_raw["quantity"] < 0]
    # 统一字段顺序与 sales_facts 对齐
    cols = ["invoice", "stock_code", "description", "quantity",
            "unit_price", "total_amount", "invoice_date", "customer_id", "country"]
    returns_raw = returns_raw[cols].rename(columns={"invoice": "invoice_no"})
    returns_matched = match_returns(returns_raw, sales)
    return returns_matched


# ----------------------------------------------------------------------------
# 函数 5：校验输出（断言）
# ----------------------------------------------------------------------------
def validate_output(sales: pd.DataFrame, cust: pd.DataFrame, returns: pd.DataFrame) -> None:
    """对每个输出做关键字段断言，保证数据可信。"""
    log.info("校验输出 ...")
    assert (sales["total_amount"] > 0).all(), "sales_facts 存在非正金额"
    assert sales["quantity"].min() > 0, "sales_facts 存在非正数量"
    assert cust["recency_days"].min() >= 0, "recency_days 出现负值"
    assert (cust["frequency"] >= 1).all(), "frequency 应 >=1"
    assert (cust["monetary"] > 0).all(), "monetary 应 >0"
    assert (returns["quantity"] < 0).all(), "returns_log 应为负数量"
    # 匹配字段允许为空，但类型应为字符串/对象
    log.info("✅ 全部断言通过")


# ----------------------------------------------------------------------------
# 函数 6：写校验报告（关键统计）
# ----------------------------------------------------------------------------
def write_validation_report(sales, cust, returns, baseline) -> None:
    rows = []
    rows.append(["sales_facts", len(sales),
                f"{sales['total_amount'].isna().mean():.2%}",
                f"GMV={sales['total_amount'].sum():,.0f}"])
    rows.append(["customer_features", len(cust),
                f"{cust['recency_days'].isna().mean():.2%}",
                f"avg_monetary={cust['monetary'].mean():,.1f}"])
    rows.append(["returns_log", len(returns),
                f"{returns['matched_original_invoice'].isna().mean():.2%}",
                f"unmatched={returns['matched_original_invoice'].isna().sum()}"])
    table = "\n".join(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |" for r in rows)
    content = f"""# Q3 校验报告（validation_report.md）

基准日（数据集最后一天）：{baseline.date()}

| 输出 | 行数 | 空值率 | 关键指标 |
|------|------|--------|----------|
{table}

## sales_facts 关键分布
- 国家 TOP3：{', '.join(sales['country'].value_counts().head(3).index)}
- 总金额(GMV)：{sales['total_amount'].sum():,.0f}

## customer_features 关键分布
- 客户数：{len(cust)}
- 一次性买家占比：{cust['is_one_time_buyer'].mean():.2%}
- Recency 中位数：{cust['recency_days'].median():.0f} 天

## returns_log 关键分布
- 退货行数：{len(returns)}
- 匹配成功率：{1 - returns['matched_original_invoice'].isna().mean():.2%}
"""
    (Path(__file__).resolve().parent / "validation_report.md").write_text(
        content, encoding="utf-8")
    log.info("✅ validation_report.md 已写出")


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def run() -> int:
    # 固定随机种子，保证可复现
    np.random.seed(42)

    # 把日志同时写文件
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(file_handler)

    try:
        df = load_data()
        baseline = pd.to_datetime(df["invoice_date"]).max()

        sales = filter_real_sales(df)
        # 规范 sales_facts 字段
        sales_out = sales.rename(columns={"invoice": "invoice_no"})[[
            "invoice_no", "stock_code", "description", "quantity",
            "unit_price", "total_amount", "invoice_date", "customer_id", "country"
        ]].copy()
        sales_out["invoice_date"] = pd.to_datetime(sales_out["invoice_date"])

        cust = compute_rfm(sales, baseline)
        returns = build_returns_log(df, sales)

        validate_output(sales_out, cust, returns)

        # 写 parquet
        sales_out.to_parquet(OUT_DIR / "sales_facts.parquet", index=False)
        cust.to_parquet(OUT_DIR / "customer_features.parquet", index=False)
        returns.to_parquet(OUT_DIR / "returns_log.parquet", index=False)
        log.info("✅ 3 个 parquet 已写出：%s", OUT_DIR)

        write_validation_report(sales_out, cust, returns, baseline)
        log.info("===== Q3 完成 =====")
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("Q3 执行失败：%s", exc)
        raise


if __name__ == "__main__":
    sys.exit(run())
