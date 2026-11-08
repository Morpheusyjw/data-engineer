# ============================================================
# 演示数据生成器（仅用于本地无 Kaggle 时预览流程，非真实数据）
# ------------------------------------------------------------
# 作用：生成一份「贴近 Online Retail II 真实脏数据特征」的合成数据，
#       使你无需 Kaggle 账号就能立刻把 Q1/Q3 跑通、看到效果。
# 真实数据：请按 SETUP.md 配置 Kaggle 后运行 `python download_data.py`，
#           它会下载真实文件覆盖本文件，报告会自动重算并去掉演示标注。
# 诚实标记：生成时会在 data/.demo 写一个标记，Q1 报告据此自动标注
#           「当前为演示合成数据」，避免把演示结论误当真实结论提交。
#
# 关键：本生成器特意构造了「退货单↔原单」对应关系，使 Q3 的退货匹配
#       能真正命中（约 95% 可匹配 + 约 5% 孤儿退货），从而验证匹配逻辑。
# ============================================================

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "online_retail_ii.csv"
rng = np.random.default_rng(42)

# ---- Country：UK 占多数，其余多国混合（和真实分布一致）----
_country_pool = (
    ["United Kingdom"] * 60
    + ["Germany", "France", "EIRE", "Spain", "Netherlands", "Belgium",
       "Switzerland", "Portugal", "Australia", "USA", "Japan", "Italy",
       "Channel Islands", "Ireland"]
)

PRODUCT_RE = r"\d+[A-Z]"  # 产品编码形如 85123A


def _make_normal_sales(n: int) -> pd.DataFrame:
    """生成 n 行「真实正向销售」。"""
    # 商品编码（数字+单字母，符合产品码正则）
    stock_code = [f"{rng.integers(10000, 99999)}{chr(rng.integers(65, 91))}" for _ in range(n)]
    mask_post = rng.random(n) < 0.02
    mask_d = rng.random(n) < 0.01
    description = []
    for i in range(n):
        if mask_post[i]:
            stock_code[i] = "POST"; description.append("POSTAGE")
        elif mask_d[i]:
            stock_code[i] = "D"; description.append("Discount")
        else:
            description.append(f"Item {stock_code[i]}")

    quantity = rng.integers(1, 101, n).astype(float)
    extreme_mask = rng.random(n) < 0.003
    quantity[extreme_mask] = rng.integers(10000, 60000, n)[extreme_mask]  # 极端大正值
    price = rng.uniform(0.5, 50, n)
    price[rng.random(n) < 0.02] = 0.0                       # 0 元（异常）
    hi_mask = rng.random(n) < 0.002
    price[hi_mask] = rng.uniform(500, 3000, n)[hi_mask]     # 异常高价
    customer_id = np.where(rng.random(n) < 0.25, np.nan, rng.integers(12345, 19900, n))  # 25% 缺失

    start = np.datetime64("2009-12-01")
    dates = start + rng.integers(0, 700, n).astype("timedelta64[D]")  # 预留 30 天给退货
    countries = (_country_pool * (n // len(_country_pool) + 1))[:n]

    df = pd.DataFrame({
        "Invoice": [str(rng.integers(536365, 590000)) for _ in range(n)],
        "StockCode": stock_code,
        "Description": description,
        "Quantity": quantity.astype(int),
        "InvoiceDate": pd.to_datetime(dates).strftime("%Y-%m-%d %H:%M:%S"),
        "Price": np.round(price, 2),
        "Customer ID": customer_id,
        "Country": countries,
    })
    for i in np.where(rng.random(n) < 0.08)[0]:
        df.loc[i, "Description"] = ""   # 部分描述缺失
    return df


def _make_returns(sales: pd.DataFrame) -> pd.DataFrame:
    """从真实销售中抽取一部分造「可匹配退货」，再加少量「孤儿退货」。"""
    # 可匹配退货：仅取「有客户ID + 产品码」的销售，复制其关键字段并取负、延后日期
    pool = sales[
        sales["Customer ID"].notna()
        & sales["StockCode"].str.fullmatch(PRODUCT_RE)
    ].sample(frac=0.18, random_state=1)

    matched = pool.copy()
    matched["Invoice"] = "C" + rng.integers(536000, 540000, len(matched)).astype(str)
    matched["Quantity"] = -matched["Quantity"].abs().astype(int)  # 与原单等量负值
    orig = pd.to_datetime(matched["InvoiceDate"])
    matched["InvoiceDate"] = (
        orig + pd.to_timedelta(rng.integers(1, 31, len(matched)), unit="D")
    ).dt.strftime("%Y-%m-%d %H:%M:%S")

    # 孤儿退货：随机客户/商品，基本无法匹配（模拟真实里偶发的无法追溯退货）
    n_orphan = max(50, int(len(matched) * 0.05))
    orphan = pd.DataFrame({
        "Invoice": ["C" + str(rng.integers(540000, 545000)) for _ in range(n_orphan)],
        "StockCode": [f"{rng.integers(10000, 99999)}{chr(rng.integers(65, 91))}" for _ in range(n_orphan)],
        "Description": ["Unknown"] * n_orphan,
        "Quantity": [-rng.integers(1, 20) for _ in range(n_orphan)],
        "InvoiceDate": [
            (pd.Timestamp("2010-06-01") + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d %H:%M:%S")
            for d in rng.integers(1, 400, n_orphan)
        ],
        "Price": np.round(rng.uniform(0.5, 50, n_orphan), 2),
        "Customer ID": rng.integers(12345, 19900, n_orphan),
        "Country": ["United Kingdom"] * n_orphan,
    })
    return pd.concat([matched, orphan], ignore_index=True)


def main() -> None:
    sales = _make_normal_sales(55_000)
    returns = _make_returns(sales)
    df = pd.concat([sales, returns], ignore_index=True)
    df = df.sample(frac=1, random_state=7).reset_index(drop=True)  # 打乱，贴近真实乱序

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    (OUT.parent / ".demo").write_text("synthetic demo data, NOT from Kaggle\n")
    n_ret = int((df["Invoice"].astype(str).str.startswith("C")).sum())
    print(f"✅ 演示数据已生成：{OUT}（{len(df):,} 行，其中取消/退货单约 {n_ret:,} 行）")
    print("   其中约 95% 退货可匹配原单，约 5% 为孤儿退货（用于验证匹配失败分支）。")
    print("   配置 Kaggle 后运行 `python download_data.py` 将下载真实数据覆盖本文件。")


if __name__ == "__main__":
    main()
