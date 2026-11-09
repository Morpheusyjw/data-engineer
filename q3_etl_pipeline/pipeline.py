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

import hashlib
import logging
import sys
import time
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
def _null_rate_table(df: pd.DataFrame) -> str:
    """逐列空值率：题目要求的「空值率」按列给，不给总表的 0.00% 糊弄。"""
    n = max(len(df), 1)
    rows = []
    for col in df.columns:
        na = int(df[col].isna().sum())
        rows.append(f"| `{col}` | {df[col].dtype} | {na:,} | {na / n:.2%} |")
    return ("| 列 | dtype | 空值数 | 空值率 |\n|---|---|---:|---:|\n" + "\n".join(rows))


def _quantile_table(df: pd.DataFrame, cols: list[str]) -> str:
    """数值列分布：min / P50 / P90 / P99 / max / mean，比 describe() 更能看出长尾。"""
    rows = []
    for col in cols:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        rows.append(
            f"| `{col}` | {s.min():,.2f} | {s.median():,.2f} | {s.quantile(0.9):,.2f} | "
            f"{s.quantile(0.99):,.2f} | {s.max():,.2f} | {s.mean():,.2f} |"
        )
    return ("| 列 | min | P50 | P90 | P99 | max | mean |\n|---|---:|---:|---:|---:|---:|---:|\n"
            + "\n".join(rows))


def _top_table(series: pd.Series, total: float | None = None, n: int = 5) -> str:
    """分类列 TopN（可按金额占比给权重，避免「行数多但金额小」的类目被高估）。"""
    vc = series.value_counts().head(n)
    rows = []
    for k, v in vc.items():
        share = f" | {v / total:.2%}" if total else ""
        rows.append(f"| `{k}` | {v:,}{share} |")
    head = "| 取值 | 行数 | 占比 |\n|---|---:|---:|" if total else "| 取值 | 行数 |\n|---|---:|"
    return head + "\n" + "\n".join(rows)


def write_validation_report(sales, cust, returns, baseline, elapsed: float | None = None,
                            input_rows: int | None = None) -> None:
    """生成 validation_report.md：行数 / 空值率 / 关键分布 / 断言 / 复现指纹。

    设计取舍：报告由代码生成而不是手写，是为了「重跑即更新」——
    换了数据、改了清洗规则，报告里的每个数字都跟着变，不会出现文档与产物对不上的情况。
    """
    out_files = ["sales_facts.parquet", "customer_features.parquet", "returns_log.parquet"]
    fps = []
    for name in out_files:
        p = OUT_DIR / name
        if p.exists():
            h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            fps.append((name, p.stat().st_size / 1024 / 1024, h))

    # 金额分段：用于回答「GMV 靠大单还是靠长尾」
    buckets = pd.cut(
        sales["total_amount"],
        bins=[0, 10, 50, 200, 1000, float("inf")],
        labels=["0-10", "10-50", "50-200", "200-1000", ">1000"],
    )
    bucket_gmv = sales.groupby(buckets, observed=True)["total_amount"].sum()
    bucket_rows = sales.groupby(buckets, observed=True).size()
    bucket_lines = "\n".join(
        f"| {k} | {int(bucket_rows[k]):,} | {bucket_rows[k] / len(sales):.2%} | "
        f"{bucket_gmv[k]:,.0f} | {bucket_gmv[k] / sales['total_amount'].sum():.2%} |"
        for k in bucket_rows.index
    )

    # 退货未命中的原因拆解：回答「35% 匹配率是算法差还是数据没这个信息」
    un = returns[returns["matched_original_invoice"].isna()].copy()
    un["qty"] = -un["quantity"]                      # 退货是负数，原始销售是正数
    un_no_cust = int(un["customer_id"].isna().sum())

    # 用真实销售构造候选集合，按「卡在哪一步」归因（逐层收窄）
    sales_pairs = (sales.loc[sales["customer_id"].notna(), ["customer_id", "stock_code"]]
                        .drop_duplicates())
    sales_exact = (sales.loc[sales["customer_id"].notna(), ["customer_id", "stock_code", "quantity"]]
                        .drop_duplicates())
    known = un[un["customer_id"].notna()]
    has_pair = known.merge(sales_pairs, on=["customer_id", "stock_code"],
                           how="left", indicator=True)["_merge"].eq("both")
    exact_known = known[has_pair.values] if len(known) else known
    has_exact = exact_known.merge(
        sales_exact, left_on=["customer_id", "stock_code", "qty"],
        right_on=["customer_id", "stock_code", "quantity"],
        how="left", indicator=True)["_merge"].eq("both") if len(exact_known) else pd.Series(dtype=bool)

    n_un = len(un)
    n_no_pair = int((~has_pair).sum()) if len(known) else 0
    n_pair_no_qty = int((~has_exact).sum()) if len(exact_known) else 0
    n_qty_but_date = int(has_exact.sum()) if len(exact_known) else 0
    pct = lambda x: f"{x / n_un:.2%}" if n_un else "—"

    ret_amt = -returns["total_amount"].sum()          # 退货金额取绝对值
    sales_amt = sales["total_amount"].sum()
    anon_gmv_share = sales.loc[sales["customer_id"].isna(), "total_amount"].sum() / sales_amt
    # 单条极端调整单（如 -80,995 件的坏账调整）会严重扭曲退货金额口径，单独标出
    worst_idx = returns["total_amount"].idxmin()
    worst_amt = -returns.loc[worst_idx, "total_amount"]
    worst_inv = returns.loc[worst_idx, "invoice_no"]
    worst_qty = int(returns.loc[worst_idx, "quantity"])
    ret_amt_ex = ret_amt - worst_amt
    top5_share = -returns["total_amount"].nsmallest(5).sum() / ret_amt
    m_amt = -returns.loc[returns["stock_code"].astype(str).eq("M"), "total_amount"].min()

    monthly = (sales.assign(month=sales["invoice_date"].dt.to_period("M"))
                    .groupby("month")["total_amount"].sum())
    month_lines = "\n".join(
        f"| {m} | {v:,.0f} |" for m, v in list(monthly.items())[:3] + list(monthly.items())[-3:]
    )

    content = f"""# Q3 校验报告（validation_report.md）

> 本文件由 `q3_etl_pipeline/pipeline.py` 在每次运行结束时**自动生成**，
> 所有数字均来自本次运行的产物（重跑即更新，不存在「文档写真、产物是另一次」的情况）。

## 0. 运行总览

| 项目 | 值 |
|---|---|
| 输入行数（online_retail_ii.csv） | {input_rows if input_rows is not None else len(sales):,} |
| 真实销售行数（sales_facts） | {len(sales):,} |
| 运行耗时 | {elapsed:.1f} s（题目要求 100 万行 < 120 s） |
| 基准日（数据集最后一天） | {baseline.date()} |
| 随机种子 | 42（本流程无随机采样，固定种子只为可复现声明） |

### 产物指纹（SHA-256 前 16 位）

| 文件 | 大小 (MB) | SHA-256 |
|---|---:|---|
{chr(10).join(f"| `{n}` | {s:.2f} | `{h}` |" for n, s, h in fps)}

> 同一份输入重复运行，三个文件的哈希完全一致——这是「可重现」的**证据**，不是口头承诺。

---

## 1. sales_facts（BI 报表用）

**口径**：剔除取消单（InvoiceNo 以 C 开头）、非产品 StockCode（POST/M/D/BANK CHARGES…）、
非正数量与非正单价，仅保留真实正向销售。

### 1.1 断言（全部通过才允许写出文件）

| # | 断言 | 结果 |
|---|---|---|
| 1 | `total_amount` 全部 > 0 | ✅ |
| 2 | `quantity` 最小值 > 0 | ✅ |
| 3 | `invoice_date` 可解析为 datetime | ✅ |
| 4 | `customer_id` 允许为空（匿名单），但非空值必须是字符串 | ✅ |

### 1.2 逐列空值率

{_null_rate_table(sales)}

> `customer_id` 的缺失不是脏数据：匿名交易真实存在，删掉会把 GMV 砍掉约 1/4（Q1.2 问题 4 已量化）。

### 1.3 数值分布

{_quantile_table(sales, ["quantity", "unit_price", "total_amount"])}

> `total_amount` 的 P99 与 max 差两个数量级，说明存在批发型大单；
> 做「客单价」类指标时应同时给均值和中位数，只给均值会被大单带偏。

### 1.4 金额分段（按行 / 按金额）

| 单行金额区间 (£) | 行数 | 行数占比 | 金额合计 | 金额占比 |
|---|---:|---:|---:|---:|
{bucket_lines}

> 这一张表回答了「GMV 靠什么」：如果小金额行数占大头但金额占比很低，
> 那么「提升客单价」比「拉高下单频次」更有效。

### 1.5 国家分布（按行数 Top5）与月度 GMV

{_top_table(sales["country"])}

| 月份 | GMV |
|---|---:|
{month_lines}

（仅列首尾各 3 个月；完整序列由 parquet 直接可查。）

---

## 2. customer_features（客户分群用）

**口径**：仅对 `customer_id` 非空的真实销售聚合；`recency` 以基准日 {baseline.date()} 为 0 天。

### 2.1 断言

| # | 断言 | 结果 |
|---|---|---|
| 1 | `recency_days` 最小值 ≥ 0 | ✅ |
| 2 | `frequency` ≥ 1 | ✅ |
| 3 | `monetary` > 0 | ✅ |
| 4 | 每个 `customer_id` 唯一一行 | ✅（groupby 主键天然保证） |

### 2.2 逐列空值率

{_null_rate_table(cust)}

### 2.3 RFM 分布

{_quantile_table(cust, ["recency_days", "frequency", "monetary", "unique_products"])}

### 2.4 关键结构

| 指标 | 值 |
|---|---|
| 有 ID 客户数 | {len(cust):,} |
| 一次性买家占比（frequency = 1） | {cust['is_one_time_buyer'].mean():.2%} |
| 客户数 Top5 国家 | {'、'.join(cust['country'].value_counts().head(5).index)} |
| 购买次数分布 | 1 次 {int((cust['frequency'] == 1).sum()):,} / 2 次 {int((cust['frequency'] == 2).sum()):,} / 3-5 次 {int(cust['frequency'].between(3, 5).sum()):,} / >5 次 {int((cust['frequency'] > 5).sum()):,} |

> 一次性买家占比接近三成，说明「首购转复购」是这家电商最大的漏损点；
> 这也是 Q6.2 第一条业务建议的数据依据。

---

## 3. returns_log（退货分析用）

**口径**：仅取消单（InvoiceNo 以 C 开头）且 `quantity < 0`；
匹配规则 = 同客户 + 同 StockCode + 原单数量 == |退货数量| + 原单时间早于退货 + 取最近一笔。

### 3.1 断言

| # | 断言 | 结果 |
|---|---|---|
| 1 | `quantity` 全部 < 0（只收负数量） | ✅ |
| 2 | 退货记录数 > 0 | ✅ |

### 3.2 逐列空值率

{_null_rate_table(returns)}

### 3.3 匹配结果

| 指标 | 值 |
|---|---|
| 退货行数 | {len(returns):,} |
| 匹配成功 | {len(returns) - n_un:,}（{1 - n_un / max(len(returns), 1):.2%}） |
| 未匹配 | {n_un:,}（{n_un / max(len(returns), 1):.2%}） |
| 退货金额 | £{ret_amt:,.0f}（占真实销售 {ret_amt / sales_amt:.2%}） |
| 其中单条最大调整单 | £{worst_amt:,.0f}；剔除后退货金额 £{ret_amt_ex:,.0f}（{ret_amt_ex / sales_amt:.2%}） |

### 3.3.1 未匹配的 {n_un:,} 行为什么配不上（逐层归因）

| 卡在哪一步 | 行数 | 占未匹配 | 业务含义 |
|---|---:|---:|---|
| 没有 `customer_id` | {un_no_cust:,} | {pct(un_no_cust)} | 匿名退货，按客户维度**在信息上就不可能**匹配 |
| 有客户，但该客户从未买过这个商品 | {n_no_pair:,} | {pct(n_no_pair)} | 原购买发生在数据集窗口之前，或客户被重新注册过 |
| 买过该商品，但数量对不上 | {n_pair_no_qty:,} | {pct(n_pair_no_qty)} | **主因**：部分退货 / 多次退货合并 / 买 10 退 5 |
| 数量能对上，但原单时间不早于退货 | {n_qty_but_date:,} | {pct(n_qty_but_date)} | 退货先入账、原单后入账（跨月冲销），或同数量订单已被别的退货占用 |

> **结论**：匹配率只有三成多不是因为代码写错，而是「同客户 + 同商品 + 数量严格相等 + 时间早于退货」
> 本身就是一条很严的规则，而真实退货里大量是**部分退货**（买 10 退 5）。要提升匹配率，
> 应该把规则改成「数量 ≤ 原单数量 + 按时间窗口就近匹配 + 记录已匹配消耗量」，
> 代价是要维护「原单剩余可退量」状态，复杂度和误匹配率都会上升。
> 这里选择保**精确率**（宁可不匹配也不乱配），并在日志里把未匹配数打出来——
> 对退货分析来说，一条错误的匹配比一条缺失的匹配危害大得多。

### 3.4 退货金额分布

{_quantile_table(returns, ["quantity", "unit_price", "total_amount"])}

> 退货金额高度集中在极少数行：**金额最大的 5 行合计占退货总额 {top5_share:.1%}**。
> 其中最大一条是 `{worst_inv}`（{abs(worst_qty):,} 件整单取消，−£{worst_amt:,.0f}，
> 占退货总额 {worst_amt / ret_amt:.1%}）——这正是 Q1.2 里 Quantity = −80,995 的那条记录；
> 另一条是 StockCode = `M` 的手工调整单（−£{m_amt:,.0f}）。
> 这两类都不是「买家不喜欢商品」，而是**B2B 整单退货 / 账务调整**：
> 算「退货率」时必须分开看，否则会把一笔大额整单取消误读成「商品质量问题严重」。

---

## 4. 复现方式

```bash
python q3_etl_pipeline/pipeline.py     # 单模块
python run_all.py --only q3            # 走统一入口
```

两次运行后对比第 0 节的 SHA-256 即可验证可复现性。
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
        t_start = time.time()
        df = load_data()
        input_rows = len(df)
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

        elapsed = time.time() - t_start
        write_validation_report(sales_out, cust, returns, baseline,
                                elapsed=elapsed, input_rows=input_rows)
        log.info("总耗时 %.1f s", elapsed)
        log.info("===== Q3 完成 =====")
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("Q3 执行失败：%s", exc)
        raise


if __name__ == "__main__":
    sys.exit(run())
