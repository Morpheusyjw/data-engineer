# ============================================================
# 共享工具：Online Retail II 数据加载与列名归一化
# ------------------------------------------------------------
# 为什么需要这个模块？
#   同一份 "Online Retail II" 数据集，在不同平台列名不一致：
#     - UCI 原始版：InvoiceNo, StockCode, Description, Quantity,
#                   InvoiceDate, UnitPrice, CustomerID, Country
#     - Kaggle(mashlyn) 版：Invoice, StockCode, Description, Quantity,
#                   InvoiceDate, Price, Customer ID, Country
#   如果代码硬编码某一套列名，换一份数据就直接崩。
#   这里把列名统一成「规范名」，下游代码只认规范名，
#   既稳健又便于 Q1 / Q3 复用，体现对真实脏数据的处理意识。
# ============================================================

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# 规范列名 -> 候选原始列名（小写、去空格后匹配）
COLUMN_ALIASES = {
    "invoice": ["invoiceno", "invoice", "invno"],
    "stock_code": ["stockcode", "stock code", "stock"],
    "description": ["description", "desc"],
    "quantity": ["quantity", "qty"],
    "invoice_date": ["invoicedate", "invoice date", "date"],
    "unit_price": ["unitprice", "unit price", "price"],
    "customer_id": ["customerid", "customer id", "custid"],
    "country": ["country", "nation"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """把原始列名映射为规范列名；找不到的列会被跳过（下游按需校验）。"""
    lower_map = {c.lower().strip(): c for c in df.columns}
    rename = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_map:
                rename[lower_map[alias]] = canonical
                break
    return df.rename(columns=rename)


def load_online_retail(path: str | Path, parse_dates: bool = True) -> pd.DataFrame:
    """加载 Online Retail II 并做列名归一化与基础类型修正。

    返回带规范列名（invoice/stock_code/...）的 DataFrame。
    注意：本函数只做「结构层」处理，不做业务清洗（清洗留给各模块）。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到数据文件：{path}。请先运行数据下载。")

    # 原始数据中部分单元格含乱码/引号，用 python 引擎更稳
    df = pd.read_csv(path, encoding="utf-8", engine="python")
    log.info("原始数据加载完成：%d 行, %d 列", len(df), df.shape[1])

    df = _normalize_columns(df)

    # 类型修正
    if "quantity" in df.columns:
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    if "unit_price" in df.columns:
        df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    if "customer_id" in df.columns:
        # 客户 ID 本质是标识符，统一成字符串，避免 123.0 这种浮点表示
        df["customer_id"] = (
            df["customer_id"].astype("string").str.replace(r"\.0$", "", regex=True)
        )
    if parse_dates and "invoice_date" in df.columns:
        df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")

    missing = [c for c in COLUMN_ALIASES if c not in df.columns]
    if missing:
        log.warning("以下规范列缺失，请检查数据源：%s", missing)
    return df
