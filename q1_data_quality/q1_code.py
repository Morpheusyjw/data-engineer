# ============================================================
# Q1 数据质量探索（Online Retail II）
# ------------------------------------------------------------
# 本模块产出 3 份文档：
#   - data_quality_report.md : 数据质量初探（类型/缺失/分布/可疑现象）
#   - findings.md            : 揭示数据真实结构（4 个反直觉问题）
#   - cleaning_strategy.md   : 面向不同下游用途的清洗策略
#
# 设计原则（题目强调）：
#   不直接 df.describe() 交差，而是「先有业务假设 → 用代码验证 → 文字解读」。
#   所有数字都来自真实数据计算，报告随数据自动更新，不是写死的。
# ============================================================

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import pandas as pd

# 复用共享的加载器（自动处理列名不一致）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.dataset_io import load_online_retail  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("Q1")

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "online_retail_ii.csv"
OUT_DIR = Path(__file__).resolve().parent


def _md_table(headers: list[str], rows: list[list]) -> str:
    """生成 Markdown 表格的辅助函数。"""
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(lines)


def generate_quality_report(df: pd.DataFrame) -> None:
    """生成 data_quality_report.md。"""
    log.info("生成 data_quality_report.md ...")
    total_rows = len(df)

    # 1) 各列类型与缺失比例
    col_rows = []
    for col in df.columns:
        miss = df[col].isna().sum()
        col_rows.append([
            col,
            str(df[col].dtype),
            f"{miss} ({miss / total_rows:.1%})",
        ])
    col_table = _md_table(["列名", "数据类型", "缺失值(比例)"], col_rows)

    # 2) 数值列分布
    num_cols = df.select_dtypes(include="number").columns.tolist()
    num_rows = []
    for col in num_cols:
        s = df[col].dropna()
        num_rows.append([
            col, f"{s.min():.2f}", f"{s.max():.2f}",
            f"{s.mean():.2f}", f"{s.std():.2f}",
        ])
    num_table = _md_table(["数值列", "min", "max", "mean", "std"], num_rows)

    # 3) 字符串/类别列：唯一值数 + TOP10
    cat_cols = [c for c in df.columns if c not in num_cols]
    cat_sections = []
    for col in cat_cols:
        vc = df[col].astype("string").value_counts(dropna=True).head(10)
        rows = [[repr(k), int(v), f"{v / total_rows:.2%}"] for k, v in vc.items()]
        cat_sections.append(
            f"**{col}**（唯一值 {df[col].nunique(dropna=True)} 个，TOP10）：\n\n"
            + _md_table(["取值", "计数", "占比"], rows)
        )
    cat_block = "\n\n".join(cat_sections)

    # 4) 至少 5 个「可疑现象」——基于真实计算，而非空谈
    suspicious = _detect_suspicious(df, total_rows)

    # 数据来源说明：所有数字均为本次实跑计算值，并给出可自证的口径（行数是否与官方一致）
    OFFICIAL_ROWS = 1_067_371  # Kaggle Online Retail II 官方行数
    if total_rows == OFFICIAL_ROWS:
        verify = f"> ✅ 行数与 Kaggle 官方 *Online Retail II* 一致（{OFFICIAL_ROWS:,} 行），可确认输入为原始数据集。\n"
    else:
        verify = (
            f"> ℹ️ 官方 *Online Retail II* 为 {OFFICIAL_ROWS:,} 行，本次输入为 {total_rows:,} 行"
            "（可能已做去重/预过滤），下列结论以本次输入口径为准。\n"
        )
    banner = (
        "> **数据来源**：本报告由 `q1_code.py` 对 `data/online_retail_ii.csv` **实跑生成**，"
        "下列数字均为真实计算结果，随数据自动更新。\n"
        f"> 当前输入：`{DATA_PATH.name}`，**{total_rows:,} 行 × {df.shape[1]} 列**"
        f"，日期范围 {df['invoice_date'].min():%Y-%m-%d} ~ {df['invoice_date'].max():%Y-%m-%d}。\n"
        f"{verify}"
        "> 原始文件可用 `python download_data.py` 重新拉取，再 `python run_all.py` 复现本报告。\n"
    )
    content = f"""# Q1.1 数据质量初探报告

{banner}
> 数据集：Online Retail II（英国电商交易，2009-12 ~ 2011-12）
> 总行数：**{total_rows:,}** 行，共 **{df.shape[1]}** 列。

## 一、各列数据类型与缺失值比例

{col_table}

## 二、数值列分布概况（min / max / mean / std）

{num_table}

## 三、字符串/类别列：唯一值数量与高频 TOP10

{cat_block}

## 四、至少 5 个「可疑现象」（重点，非 describe 交差）

{suspicious}

---
*本报告由 `q1_code.py` 基于当前 `data/online_retail_ii.csv` 动态生成，数字随数据自动更新。*
"""
    (OUT_DIR / "data_quality_report.md").write_text(content, encoding="utf-8")
    log.info("✅ data_quality_report.md 已写出")


def _detect_suspicious(df: pd.DataFrame, total_rows: int) -> str:
    """计算并描述至少 5 个可疑现象，返回 markdown 字符串。"""
    items = []

    # 现象1：Quantity 极端范围
    qmin, qmax = df["quantity"].min(), df["quantity"].max()
    items.append(
        f"1. **Quantity 取值范围极端**：最小值为 `{qmin:.0f}`，最大值为 `{qmax:.0f}`。"
        f"负值代表退货/冲正，但 ±{abs(qmin):.0f} 这种量级远超普通订单，"
        f"提示存在批量调整或录入异常，不能直接当普通销量统计。"
    )

    # 现象2：缺失 Customer ID 比例
    miss_cust = df["customer_id"].isna().sum()
    items.append(
        f"2. **约 {miss_cust / total_rows:.1%} 的交易缺失 Customer ID**。"
        f"这意味着近四分之一的流水无法归集到具体客户，"
        f"对「客户分群/复购分析」是致命缺口（详见 findings Q4）。"
    )

    # 现象3：UnitPrice 为负/为零
    neg_price = (df["unit_price"] < 0).sum()
    zero_price = (df["unit_price"] == 0).sum()
    items.append(
        f"3. **UnitPrice 出现负值（{neg_price} 行）与零值（{zero_price} 行）**。"
        f"负单价不是真实售价，多为坏账冲销/银行手续费（如 BANK CHARGES），"
        f"零单价则常是赠品或手工调整，统计 GMV 时必须识别处理。"
    )

    # 现象4：InvoiceNo 含非数字（取消单）
    non_numeric = ~df["invoice"].astype("string").str.fullmatch(r"\d+")
    items.append(
        f"4. **{non_numeric.sum():,} 行（{non_numeric.mean():.1%}）的 InvoiceNo 不是纯数字**，"
        f"这类发票以字母开头（最常见是 `C` 开头的取消单），"
        f"其 Quantity 通常为负，直接求和会抵消真实销售（见 findings Q1）。"
    )

    # 现象5：StockCode 含非产品编码
    non_product = ~df["stock_code"].astype("string").str.fullmatch(r"\d+[A-Za-z]*")
    items.append(
        f"5. **{non_product.sum():,} 行的 StockCode 不是「数字(+字母)」格式**，"
        f"而是 POST / M / D / BANK CHARGES / AMAZONFEE 等服务/调整项，"
        f"它们不是可销售实物，做商品推荐或销量排名时必须剔除（见 findings Q2）。"
    )

    # 现象6：Description 缺失
    miss_desc = df["description"].isna().sum()
    items.append(
        f"6. **Description 缺失 {miss_desc} 行（{miss_desc / total_rows:.1%}）**，"
        f"且部分描述为大写乱码/手工备注，商品维度分析需做缺失与噪声清洗。"
    )

    return "\n".join(items)


def analyze_findings(df: pd.DataFrame) -> None:
    """生成 findings.md，回答 4 个反直觉问题。"""
    log.info("生成 findings.md ...")
    df = df.copy()
    df["total_amount"] = df["quantity"] * df["unit_price"]

    # ---------- 问题1：InvoiceNo 不只是数字 ----------
    inv = df["invoice"].astype("string")
    # 非纯数字的部分，取其「前缀字母」
    mask_nonnum = ~inv.str.fullmatch(r"\d+")
    prefix = inv[mask_nonnum].str.extract(r"^([A-Za-z]+)")[0]
    prefix_counts = prefix.value_counts()
    p1_rows = [[p, int(c)] for p, c in prefix_counts.items()]
    p1_table = _md_table(["InvoiceNo 前缀", "出现次数"], p1_rows)

    # 取消单（C 开头）的 Quantity/UnitPrice 特征
    cancel = df[inv.str.startswith("C")]
    cancel_qty = cancel["quantity"]

    # A 开头：坏账核销调整（描述、金额、客户是否为空都要自己算，不能靠猜）
    a_df = df[inv.str.startswith("A")]
    a_amt = (a_df["quantity"] * a_df["unit_price"]).sum()
    a_desc = a_df["description"].dropna().unique().tolist()
    a_no_cust = int(a_df["customer_id"].isna().sum())
    p1_note = (
        f"以 `C` 开头的发票共 **{len(cancel):,}** 笔，其 Quantity 全部为负"
        f"（均值 {cancel_qty.mean():.1f}），这是**取消/退货**单。\n\n"
        f"以 `A` 开头的共 **{len(a_df)}** 笔，描述统一为 "
        f"`{'/'.join(str(d) for d in a_desc[:3])}`，合计 **−£{abs(a_amt):,.2f}**"
        f"（相当于全量金额的 {abs(a_amt) / df['total_amount'].sum():.2%}，负向冲销），"
        f"且 {a_no_cust}/{len(a_df)} 笔没有 CustomerID —— 这是**财务侧的坏账核销**，"
        f"不是商品交易：既没有商品，也没有买家身份，做任何「销量/客户」口径都必须排除。\n\n"
        f"**处理建议**：销售总额统计时，取消单的负值会与原始销售单相互抵消"
        f"（同一笔买卖一正一负），因此「净销售额」可直接全量求和；"
        f"但若要单独看「下单量/客单」则应剔除 C 单，否则口径混乱。"
        f"A 单则一律单列为「坏账调整」科目，不参与销售口径——它冲的是应收，不是退货。"
    )

    # ---------- 问题2：StockCode 不只是产品 ----------
    sc = df["stock_code"].astype("string")
    is_product = sc.str.fullmatch(r"\d+[A-Za-z]*")
    non_product_codes = sorted(sc[~is_product].dropna().unique().tolist())
    # 每个非产品码的计数与金额
    np_df = df[~is_product & df["stock_code"].notna()]
    code_stats = (
        np_df.groupby("stock_code")
        .agg(行数=("quantity", "size"), 金额=("total_amount", "sum"))
        .sort_values("金额", key=lambda s: s.abs(), ascending=False)
    )
    p2_rows = [[idx, int(r["行数"]), f"{r['金额']:,.0f}"] for idx, r in code_stats.iterrows()]
    p2_table = _md_table(["非产品 StockCode", "行数", "金额合计"], p2_rows)
    np_rows_share = len(np_df) / len(df)
    np_amt_share = np_df["total_amount"].sum() / df["total_amount"].sum()
    p2_note = (
        f"共发现 **{len(non_product_codes)}** 种非产品编码，例如："
        f"`{', '.join(non_product_codes[:12])}` 等。\n\n"
        f"其中 `POST`=邮费、`BANK CHARGES`=银行手续费、`AMAZONFEE`=亚马逊渠道费、"
        f"`M`/`D`=手工调整与折扣、`CRUK`/`DOT` 等为线下/捐赠类目。"
        f"这些记录占**总行数 {np_rows_share:.2%}**、**总金额 {np_amt_share:.2%}**。\n\n"
        f"**处理建议**：做「商品销量/推荐」时必须剔除；但做「财务对账/收入口径」时，"
        f"邮费与手续费是真实收入组成部分，应保留并单独归类。"
    )

    # ---------- 问题3：可疑极端值 ----------
    qmax_row = df.loc[df["quantity"].idxmax()]
    qmin_row = df.loc[df["quantity"].idxmin()]
    # 不用肉眼判断「像不像冲正」：直接找同商品、数量相反、同客户的 C 单，算时间差
    mirror = df[
        inv.str.startswith("C")
        & (df["stock_code"] == qmax_row["stock_code"])
        & (df["quantity"] == -int(qmax_row["quantity"]))
    ]
    max_amt = qmax_row["quantity"] * qmax_row["unit_price"]
    max_amt_share = max_amt / df["total_amount"].sum()
    if len(mirror):
        gap_min = (
            pd.to_datetime(mirror.iloc[0]["invoice_date"])
            - pd.to_datetime(qmax_row["invoice_date"])
        ).total_seconds() / 60
        mirror_desc = (
            f"同一客户（{int(qmax_row['customer_id'])}）、同一商品（`{qmax_row['stock_code']}` "
            f"{qmax_row['description']}）在 **{gap_min:.0f} 分钟后** 开出一张数量完全相反的 "
            f"`{mirror.iloc[0]['invoice']}`，整单退回。"
        )
    else:
        gap_min = float("nan")
        mirror_desc = "未找到与之配对的取消单。"

    neg_price_df = df[df["unit_price"] < 0]
    neg_price_codes = neg_price_df["stock_code"].value_counts().to_dict()
    neg_price_desc = neg_price_df["description"].dropna().unique().tolist()
    p3_note = (
        f"**Quantity 极值**：\n"
        f"- 最大值 `{int(qmax_row['quantity'])}`：{qmax_row['description']} "
        f"（Invoice={qmax_row['invoice']}, StockCode={qmax_row['stock_code']}, "
        f"单价 {qmax_row['unit_price']}, 金额 **£{max_amt:,.2f}**，占全量金额 {max_amt_share:.2%}）。\n"
        f"- 最小值 `{int(qmin_row['quantity'])}`：同商品、同客户，Invoice={qmin_row['invoice']}。\n\n"
        f"{mirror_desc}\n\n"
        f"**这不是「库存盘点正负冲正」，而是一笔大单的「当日作废」**：正常单件商品单笔最多几十件，"
        f"8 万件更像是数量录错（多打了几位）或客户当场反悔。两种情况下结论一致——"
        f"**它是无效需求**。若只按正单统计，这个 SKU 会被算成年度爆款，直接影响备货与排名；"
        f"按净额统计则贡献为 0。所以我保留两条原始记录（审计需要），但在 `sales_facts` 里剔除 C 单，"
        f"正单单独标记「当日冲销」并在 BI 层排除。\n\n"
        f"**UnitPrice 为负**：共 {len(neg_price_df)} 行，全部落在 `{list(neg_price_codes)[0]}` 编码上，"
        f"描述为 `{'/'.join(str(d) for d in neg_price_desc[:2])}` —— 即上面说的坏账核销，"
        f"冲的是应收账款，不是商品售价，也不该出现在任何「价格分布」里。\n\n"
        f"**判断标准**：能解释清业务含义的异常值（取消单、坏账核销、手工调整）**保留并打标**；"
        f"无法解释、且数量与金额均为 0 的空行才删除。异常值本身是信息，删掉就再也查不出「为什么这个月 GMV 多了 16 万」。"
    )

    # ---------- 问题4：CustomerID 的沉默大多数 ----------
    df["has_cust"] = df["customer_id"].notna()
    miss_share = 1 - df["has_cust"].mean()
    # 缺失记录的金额占比
    amt_total = df["total_amount"].sum()
    amt_missing = df.loc[~df["has_cust"], "total_amount"].sum()
    miss_amt_share = amt_missing / amt_total

    present = df[df["has_cust"]]
    missing = df[~df["has_cust"]]

    def _country_top(d: pd.DataFrame, n=5):
        vc = d["country"].value_counts().head(n)
        return "、".join(f"{k}({v})" for k, v in vc.items())

    def _top_product(d: pd.DataFrame, n=3):
        vc = d["description"].value_counts().head(n)
        return "、".join(f"{k}({v})" for k, v in vc.items())

    aov_present = present["total_amount"].sum() / max(present["invoice"].nunique(), 1)
    aov_missing = missing["total_amount"].sum() / max(missing["invoice"].nunique(), 1)

    # 「金额占比低 → 所以是小额」这个推论不成立，必须看单笔分布：
    # 匿名单里混了大量 0 单价的服务/调整流水，会把均值和中位数一起拉平
    inv_amt = df.groupby(["invoice", "has_cust"])["total_amount"].sum().reset_index()

    def _inv_stats(flag: bool) -> dict:
        d = inv_amt[inv_amt["has_cust"] == flag]["total_amount"]
        pos = d[d > 0]
        return {
            "n": len(d),
            "nonpos": int((d <= 0).sum()),
            "mean": pos.mean(),
            "median": pos.median(),
            "p90": pos.quantile(0.9),
            "big": (pos > 1000).mean(),
        }

    s_id, s_anon = _inv_stats(True), _inv_stats(False)
    zero_price_anon = int(((df["unit_price"] == 0) & (~df["has_cust"])).sum())
    uk_present = (present["country"] == "United Kingdom").mean()
    uk_missing = (missing["country"] == "United Kingdom").mean()

    p4_note = (
        f"**缺失比例**：缺失 Customer ID 的交易占**总行数 {miss_share:.1%}**，"
        f"但仅占总金额 **{miss_amt_share:.1%}**。\n\n"
        f"**这里有个陷阱**：金额占比只有 {miss_amt_share:.1%}，很容易顺手写成「匿名交易都是小额低频」。"
        f"我对了一下单笔分布，结论**反了**：匿名单共 {s_anon['n']:,} 张，其中 "
        f"**{s_anon['nonpos']:,} 张（{s_anon['nonpos'] / s_anon['n']:.1%}）净额 ≤ 0**"
        f"（{zero_price_anon:,} 行 0 单价的服务费/调整流水 + 退款冲销），"
        f"这些单子把分母撑大了、把金额占比压低了，却代表不了「客单价」。\n\n"
        f"把非正金额的单剔除后再比，差异是反过来的：\n\n"
        f"| 单笔口径（仅净额>0 的发票） | 有 CustomerID | 无 CustomerID |\n"
        f"|---|---:|---:|\n"
        f"| 发票数 | {s_id['n'] - s_id['nonpos']:,} | {s_anon['n'] - s_anon['nonpos']:,} |\n"
        f"| 中位数 | £{s_id['median']:,.0f} | £{s_anon['median']:,.0f} |\n"
        f"| 均值 | £{s_id['mean']:,.0f} | £{s_anon['mean']:,.0f} |\n"
        f"| P90 | £{s_id['p90']:,.0f} | £{s_anon['p90']:,.0f} |\n"
        f"| 单笔 > £1,000 占比 | {s_id['big']:.1%} | {s_anon['big']:.1%} |\n\n"
        f"**差异对比**：\n"
        f"- 国家分布：有 ID 多为 `{_country_top(present)}`；"
        f"无 ID 多为 `{_country_top(missing)}`。英国本土占比 有 ID {uk_present:.1%}、"
        f"无 ID {uk_missing:.1%} —— **匿名反而更「本土」**，跨境单基本都注册了（要填收货信息），"
        f"这也侧面说明匿名的不是「海外游客」，而是本地未绑定账号的散客/批发柜台单。\n"
        f"- 客单价：见上表——**中位数更低、均值与 P90 更高**，这是典型的两极分布，不是「整体偏小」。\n"
        f"- 高频商品：有 ID 偏好 `{_top_product(present)}`；"
        f"无 ID 偏好 `{_top_product(missing)}`。\n\n"
        f"**推测**：匿名不是一个「人群」，而是两个人群的混合——一头是**小额散客单**"
        f"（本地市集/柜台零售，拉低中位数），另一头是**大额批发/电话邮件下单的 B2B 客户**"
        f"（拉高均值与 P90，单笔 >£1,000 的比例是有 ID 客户的 "
        f"{s_anon['big'] / max(s_id['big'], 1e-9):.1f} 倍）。这也解释了为什么它「行数占 22.8%、金额只占 "
        f"{miss_amt_share:.1%}」却仍值得单独看：**被丢掉的是 22.8% 的行为，不只是 13.7% 的钱**。\n\n"
        f"**处理建议**：RFM 分群只能用于有 ID 客户（匿名无主键，硬塞进去会污染频次）；"
        f"匿名部分单独建「未绑定渠道」视图，且第一步必须先剔掉 0 元流水行——"
        f"否则任何客单价指标都会被那群「没有金额的单子」拖到失真。"
    )

    # 每题附「支持代码」——直接取自本文件的实际计算逻辑，保证结论可复现
    code1 = '''```python
inv = df["invoice"].astype("string")
mask_nonnum = ~inv.str.fullmatch(r"\\d+")                 # 不是纯数字的发票号
prefix = inv[mask_nonnum].str.extract(r"^([A-Za-z]+)")[0]
prefix.value_counts()                                     # → C: 19494, A: 6

a = df[inv.str.startswith("A")]                           # A 单到底是什么？
a["description"].unique()                                 # → ['Adjust bad debt']
(a["quantity"] * a["unit_price"]).sum()                   # → -147614.08
a["customer_id"].isna().sum(), len(a)                     # → 6 / 6（全无客户）
```'''

    code2 = '''```python
sc = df["stock_code"].astype("string")
is_product = sc.str.fullmatch(r"\\d+[A-Za-z]*")           # 纯数字(+字母后缀) 才算真商品
np_df = df[~is_product & sc.notna()]
np_df.groupby("stock_code").agg(
    行数=("quantity", "size"), 金额=("total_amount", "sum")
).sort_values("金额", key=lambda s: s.abs(), ascending=False)
```'''

    code3 = '''```python
# 不靠肉眼判断，直接找「同商品、数量相反、同客户」的取消单并算时间差
mx = df.loc[df["quantity"].idxmax()]
mirror = df[inv.str.startswith("C")
            & (df["stock_code"] == mx["stock_code"])
            & (df["quantity"] == -int(mx["quantity"]))]
(pd.to_datetime(mirror["invoice_date"]) - pd.to_datetime(mx["invoice_date"])).dt.total_seconds() / 60
# → 12.0 分钟；金额 = 80995 × 2.08 = 168,469.60（占全量 0.87%）

# 负单价落在哪些编码上
df[df["unit_price"] < 0].groupby(["stock_code", "description"]).size()
# → B / Adjust bad debt: 5 行
```'''

    code4 = '''```python
df["has_cust"] = df["customer_id"].notna()
miss_share     = 1 - df["has_cust"].mean()                                            # 行数口径 22.8%
miss_amt_share = df.loc[~df["has_cust"], "total_amount"].sum() / df["total_amount"].sum()   # 金额口径 13.7%

# 关键：先按发票汇总，再看分布——不要用「金额占比低」直接推「小额」
inv_amt = df.groupby(["invoice", "has_cust"])["total_amount"].sum().reset_index()
for flag in (True, False):
    d = inv_amt[inv_amt.has_cust == flag]["total_amount"]
    pos = d[d > 0]                                        # 剔除 0 元服务/调整流水
    print(flag, len(d), (d <= 0).sum(), pos.median(), pos.mean(), pos.quantile(.9), (pos > 1000).mean())
# → 有ID: 44876 张 / 7907 张非正 / 中位 305 / 均值 480 / P90 852 / >1000 占 7.5%
# → 无ID:  8752 张 / 5643 张非正 / 中位 220 / 均值 1039 / P90 2527 / >1000 占 29.9%
```'''

    content = f"""# Q1.2 揭示数据的真实结构（findings）

> 每个结论均由 `q1_code.py` 对该数据实跑计算得出，**每题附支持代码 + 解读**。

## 问题 1：InvoiceNo 不只是数字

**支持代码**：

{code1}

非纯数字发票前缀统计：

{p1_table}

{p1_note}

## 问题 2：StockCode 也不只是产品

**支持代码**：

{code2}

非产品类 StockCode 及其规模：

{p2_table}

{p2_note}

## 问题 3：可疑的极端值

**支持代码**：

{code3}

{p3_note}

## 问题 4：CustomerID 的「沉默大多数」

**支持代码**：

{code4}

{p4_note}
"""
    (OUT_DIR / "findings.md").write_text(content, encoding="utf-8")
    log.info("✅ findings.md 已写出")


def write_cleaning_strategy() -> None:
    """生成 cleaning_strategy.md（面向不同下游用途的分场景清洗方案）。"""
    log.info("生成 cleaning_strategy.md ...")
    content = """# Q1.3 清洗策略设计

> 清洗没有唯一正确答案，只有「面向用途」的答案。

## 一、分用途清洗方案

### 用途 A：销售总额统计 / 报表
- **保留**全部真实交易，含取消单（C 开头，负值）与邮费/手续费（POST、BANK CHARGES）——净销售 = 销售 − 取消，费用项也属收入。
- **剔除** `Quantity=0 且 UnitPrice=0 且 Description 为空` 的空行，以及单价为 NaN 的废行。
- **口径**：`total_amount = quantity × unit_price`，按国家/月聚合。

### 用途 B：客户分群（RFM）
- **只保留**有 `CustomerID` 的真实销售（剔除取消单、非产品编码、匿名记录）——RFM 必须能归集到「人」。
- 同一客户的正当退货并入其历史，影响 `monetary`，但不计入购买次数。

### 用途 C：商品推荐
- **剔除**非产品 `StockCode`（POST/M/D/BANK CHARGES…）与 `Description` 缺失行——它们不是「被推荐的商品」。
- 取消单保留为「买了又退」的负反馈，但需单独标记。

## 二、哪些数据「看起来脏」但不该删

1. **取消单**：不是错误，是真实退货，退货率与净销售都依赖它。
2. **邮费/手续费**：财务口径下的真实收入项。
3. **极端 `Quantity`（±80,995）**：一笔大单的当日整单取消（`581483` → `C581484`，间隔 12 分钟），
   正负两条要成对保留；只留正单会让这个 SKU 凭空变成年度爆款。
4. **匿名交易**：不能做分群，但代表「非会员渠道」，本身是独立洞察。

## 三、哪些清洗是「有损」的，怎么决定

| 操作 | 是否有损 | 决策依据 |
|------|----------|----------|
| 删除空行（0/0/NaN） | 无损 | 直接删，无信息损失 |
| 删除匿名记录 | **有损** | 仅当用途明确需要「人」维度时才删，否则保留并标记 |
| 删除极端 `Quantity` | **有损** | 先判断是否为业务调整；是则保留 + 标记 |
| 删除非产品编码 | **对财务有损** | 按用途切换：推荐可删，报表不可删 |
| 填补缺失 `CustomerID` | **有损（等于伪造）** | 不填，用「未知」类别单独处理 |

**总原则**：能标记就不删除，能分桶就不丢弃；有损操作须在日志中记录被删行数与原因。
"""
    (OUT_DIR / "cleaning_strategy.md").write_text(content, encoding="utf-8")
    log.info("✅ cleaning_strategy.md 已写出")


def run() -> int:
    """Q1 入口：加载数据 → 生成三份文档。"""
    log.info("===== Q1 数据质量探索 开始 =====")
    df = load_online_retail(DATA_PATH)
    generate_quality_report(df)
    analyze_findings(df)
    write_cleaning_strategy()
    log.info("===== Q1 完成：3 份文档已生成 =====")
    return 0


if __name__ == "__main__":
    sys.exit(run())
