# Q1.2 揭示数据的真实结构（findings）

> 每个结论均由 `q1_code.py` 对该数据实跑计算得出，**每题附支持代码 + 解读**。

## 问题 1：InvoiceNo 不只是数字

**支持代码**：

```python
inv = df["invoice"].astype("string")
mask_nonnum = ~inv.str.fullmatch(r"\d+")                 # 不是纯数字的发票号
prefix = inv[mask_nonnum].str.extract(r"^([A-Za-z]+)")[0]
prefix.value_counts()                                     # → C: 19494, A: 6

a = df[inv.str.startswith("A")]                           # A 单到底是什么？
a["description"].unique()                                 # → ['Adjust bad debt']
(a["quantity"] * a["unit_price"]).sum()                   # → -147614.08
a["customer_id"].isna().sum(), len(a)                     # → 6 / 6（全无客户）
```

非纯数字发票前缀统计：

| InvoiceNo 前缀 | 出现次数 |
| --- | --- |
| C | 19494 |
| A | 6 |

以 `C` 开头的发票共 **19,494** 笔，其 Quantity 全部为负（均值 -25.2），这是**取消/退货**单。

以 `A` 开头的共 **6** 笔，描述统一为 `Adjust bad debt`，合计 **−£147,614.08**（相当于全量金额的 0.77%，负向冲销），且 6/6 笔没有 CustomerID —— 这是**财务侧的坏账核销**，不是商品交易：既没有商品，也没有买家身份，做任何「销量/客户」口径都必须排除。

**处理建议**：销售总额统计时，取消单的负值会与原始销售单相互抵消（同一笔买卖一正一负），因此「净销售额」可直接全量求和；但若要单独看「下单量/客单」则应剔除 C 单，否则口径混乱。A 单则一律单列为「坏账调整」科目，不参与销售口径——它冲的是应收，不是退货。

## 问题 2：StockCode 也不只是产品

**支持代码**：

```python
sc = df["stock_code"].astype("string")
is_product = sc.str.fullmatch(r"\d+[A-Za-z]*")           # 纯数字(+字母后缀) 才算真商品
np_df = df[~is_product & sc.notna()]
np_df.groupby("stock_code").agg(
    行数=("quantity", "size"), 金额=("total_amount", "sum")
).sort_values("金额", key=lambda s: s.abs(), ascending=False)
```

非产品类 StockCode 及其规模：

| 非产品 StockCode | 行数 | 金额合计 |
| --- | --- | --- |
| DOT | 1446 | 322,647 |
| AMAZONFEE | 43 | -260,764 |
| B | 6 | -147,614 |
| POST | 2122 | 112,341 |
| M | 1421 | -82,796 |
| BANK CHARGES | 102 | -35,563 |
| D | 177 | -13,485 |
| C2 | 282 | 13,386 |
| CRUK | 16 | -7,933 |
| ADJUST | 67 | 6,835 |
| S | 104 | -6,066 |
| ADJUST2 | 3 | 731 |
| gift_0001_30 | 29 | 610 |
| gift_0001_20 | 29 | 471 |
| DCGSSGIRL | 25 | 296 |
| DCGS0076 | 15 | 292 |
| gift_0001_50 | 8 | 254 |
| DCGSSBOY | 23 | 251 |
| TEST001 | 15 | 202 |
| gift_0001_40 | 7 | 166 |
| gift_0001_10 | 16 | 126 |
| DCGS0069 | 6 | 80 |
| DCGS0004 | 5 | 68 |
| gift_0001_70 | 3 | 60 |
| PADS | 19 | -37 |
| DCGS0058 | 31 | 35 |
| DCGS0003 | 14 | 33 |
| DCGS0070 | 3 | 25 |
| DCGS0072 | 4 | 21 |
| DCGS0066N | 4 | 17 |
| DCGS0068 | 3 | 17 |
| 47503J  | 1 | 16 |
| m | 5 | 15 |
| SP1002 | 3 | 15 |
| DCGS0075 | 1 | 13 |
| DCGS0037 | 2 | 13 |
| DCGS0041 | 1 | 5 |
| DCGS0044 | 1 | 3 |
| DCGS0062 | 2 | 3 |
| TEST002 | 2 | 1 |
| C3 | 1 | 0 |
| gift_0001_60 | 2 | 0 |
| gift_0001_80 | 4 | 0 |
| DCGS0016 | 1 | 0 |
| DCGS0027 | 1 | 0 |
| DCGS0036 | 1 | 0 |
| DCGS0039 | 1 | 0 |
| gift_0001_90 | 2 | 0 |
| DCGS0006 | 1 | 0 |
| DCGS0067 | 1 | 0 |
| DCGS0066P | 1 | 0 |
| DCGS0055 | 1 | 0 |
| GIFT | 1 | 0 |
| DCGS0056 | 1 | 0 |
| DCGS0057 | 1 | 0 |
| DCGS0059 | 1 | 0 |
| DCGSLGIRL | 1 | 0 |
| DCGSLBOY | 1 | 0 |
| DCGS0060 | 1 | 0 |
| DCGS0074 | 1 | 0 |
| DCGS0073 | 1 | 0 |
| DCGS0071 | 1 | 0 |
| DCGS0053 | 1 | 0 |

共发现 **63** 种非产品编码，例如：`47503J , ADJUST, ADJUST2, AMAZONFEE, B, BANK CHARGES, C2, C3, CRUK, D, DCGS0003, DCGS0004` 等。

其中 `POST`=邮费、`BANK CHARGES`=银行手续费、`AMAZONFEE`=亚马逊渠道费、`M`/`D`=手工调整与折扣、`CRUK`/`DOT` 等为线下/捐赠类目。这些记录占**总行数 0.57%**、**总金额 -0.49%**。

**处理建议**：做「商品销量/推荐」时必须剔除；但做「财务对账/收入口径」时，邮费与手续费是真实收入组成部分，应保留并单独归类。

## 问题 3：可疑的极端值

**支持代码**：

```python
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
```

**Quantity 极值**：
- 最大值 `80995`：PAPER CRAFT , LITTLE BIRDIE （Invoice=581483, StockCode=23843, 单价 2.08, 金额 **£168,469.60**，占全量金额 0.87%）。
- 最小值 `-80995`：同商品、同客户，Invoice=C581484。

同一客户（16446）、同一商品（`23843` PAPER CRAFT , LITTLE BIRDIE）在 **12 分钟后** 开出一张数量完全相反的 `C581484`，整单退回。

**这不是「库存盘点正负冲正」，而是一笔大单的「当日作废」**：正常单件商品单笔最多几十件，8 万件更像是数量录错（多打了几位）或客户当场反悔。两种情况下结论一致——**它是无效需求**。若只按正单统计，这个 SKU 会被算成年度爆款，直接影响备货与排名；按净额统计则贡献为 0。所以我保留两条原始记录（审计需要），但在 `sales_facts` 里剔除 C 单，正单单独标记「当日冲销」并在 BI 层排除。

**UnitPrice 为负**：共 5 行，全部落在 `B` 编码上，描述为 `Adjust bad debt` —— 即上面说的坏账核销，冲的是应收账款，不是商品售价，也不该出现在任何「价格分布」里。

**判断标准**：能解释清业务含义的异常值（取消单、坏账核销、手工调整）**保留并打标**；无法解释、且数量与金额均为 0 的空行才删除。异常值本身是信息，删掉就再也查不出「为什么这个月 GMV 多了 16 万」。

## 问题 4：CustomerID 的「沉默大多数」

**支持代码**：

```python
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
```

**缺失比例**：缺失 Customer ID 的交易占**总行数 22.8%**，但仅占总金额 **13.7%**。

**这里有个陷阱**：金额占比只有 13.7%，很容易顺手写成「匿名交易都是小额低频」。我对了一下单笔分布，结论**反了**：匿名单共 8,752 张，其中 **5,643 张（64.5%）净额 ≤ 0**（6,131 行 0 单价的服务费/调整流水 + 退款冲销），这些单子把分母撑大了、把金额占比压低了，却代表不了「客单价」。

把非正金额的单剔除后再比，差异是反过来的：

| 单笔口径（仅净额>0 的发票） | 有 CustomerID | 无 CustomerID |
|---|---:|---:|
| 发票数 | 36,969 | 3,109 |
| 中位数 | £305 | £220 |
| 均值 | £480 | £1,039 |
| P90 | £852 | £2,528 |
| 单笔 > £1,000 占比 | 7.5% | 29.9% |

**差异对比**：
- 国家分布：有 ID 多为 `United Kingdom(741301)、Germany(17624)、EIRE(16195)、France(14202)、Netherlands(5140)`；无 ID 多为 `United Kingdom(240029)、EIRE(1671)、Hong Kong(364)、Unspecified(232)、France(128)`。英国本土占比 有 ID 89.9%、无 ID 98.8% —— **匿名反而更「本土」**，跨境单基本都注册了（要填收货信息），这也侧面说明匿名的不是「海外游客」，而是本地未绑定账号的散客/批发柜台单。
- 客单价：见上表——**中位数更低、均值与 P90 更高**，这是典型的两极分布，不是「整体偏小」。
- 高频商品：有 ID 偏好 `WHITE HANGING HEART T-LIGHT HOLDER(5315)、REGENCY CAKESTAND 3 TIER(3777)、ASSORTED COLOUR BIRD ORNAMENT(2794)`；无 ID 偏好 `DOTCOM POSTAGE(1428)、JUMBO BAG RED RETROSPOT(693)、JUMBO STORAGE BAG SUKI(635)`。

**推测**：匿名不是一个「人群」，而是两个人群的混合——一头是**小额散客单**（本地市集/柜台零售，拉低中位数），另一头是**大额批发/电话邮件下单的 B2B 客户**（拉高均值与 P90，单笔 >£1,000 的比例是有 ID 客户的 4.0 倍）。这也解释了为什么它「行数占 22.8%、金额只占 13.7%」却仍值得单独看：**被丢掉的是 22.8% 的行为，不只是 13.7% 的钱**。

**处理建议**：RFM 分群只能用于有 ID 客户（匿名无主键，硬塞进去会污染频次）；匿名部分单独建「未绑定渠道」视图，且第一步必须先剔掉 0 元流水行——否则任何客单价指标都会被那群「没有金额的单子」拖到失真。
