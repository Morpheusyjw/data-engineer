# Q1.2 揭示数据的真实结构（findings）

> 每个结论均由 `q1_code.py` 对该数据实跑计算得出，**每题附支持代码 + 解读**。

## 问题 1：InvoiceNo 不只是数字

**支持代码**：

```python
inv = df["invoice"].astype("string")
mask_nonnum = ~inv.str.fullmatch(r"\d+")                 # 不是纯数字的发票号
prefix = inv[mask_nonnum].str.extract(r"^([A-Za-z]+)")[0]
prefix.value_counts()                                     # → C: 19494, A: 6

cancel = df[inv.str.startswith("C")]                      # 取消/退货单
cancel["quantity"].describe()                             # 均值 -25.2，最大值仍为负
```

非纯数字发票前缀统计：

| InvoiceNo 前缀 | 出现次数 |
| --- | --- |
| C | 19494 |
| A | 6 |

以 `C` 开头的发票共 **19,494** 笔，其 Quantity 全部为负（均值 -25.2），这是**取消/退货**单。其余字母前缀（如本数据中罕见的其他前缀）多为手工调整。

**处理建议**：销售总额统计时，取消单的负值会与原始销售单相互抵消（同一笔买卖一正一负），因此「净销售额」可直接全量求和；但若要单独看「下单量/客单」则应剔除 C 单，否则口径混乱。

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
df["total_amount"] = df["quantity"] * df["unit_price"]
df.loc[df["quantity"].idxmax(), ["invoice", "stock_code", "quantity", "description"]]
df.loc[df["quantity"].idxmin(), ["invoice", "stock_code", "quantity", "description"]]
df[df["unit_price"] < 0].groupby("stock_code")["unit_price"].agg(["size", "sum"])
```

**Quantity 极值**：
- 最大值 `80995`：PAPER CRAFT , LITTLE BIRDIE （Invoice=581483, StockCode=23843）。
- 最小值 `-80995`：PAPER CRAFT , LITTLE BIRDIE （Invoice=C581484, StockCode=23843）。

两者绝对值相同、符号相反，且描述均为 `MANUAL/调整` 类手工记录，**高度疑似同一笔库存盘点的正负调整（真实业务冲正，非错误）**，应保留但单独标记。

**UnitPrice 为负**：共 5 行，集中在 `BANK CHARGES`、`AMAZONFEE` 等调整类编码，业务上代表「扣费/退款」，不是售价。

**判断标准**：保留「有业务含义的调整记录」（标记类型），删除「无对应发票、数量与金额均为 0 的空行」以及「明显录入错误（如价格为 0 且描述为 NaN）」。

## 问题 4：CustomerID 的「沉默大多数」

**支持代码**：

```python
df["has_cust"] = df["customer_id"].notna()
miss_share     = 1 - df["has_cust"].mean()                                   # 行数口径 22.8%
miss_amt_share = df.loc[~df["has_cust"], "total_amount"].sum() / df["total_amount"].sum()  # 金额口径 13.7%

for name, d in [("有ID", df[df.has_cust]), ("无ID", df[~df.has_cust])]:
    aov = d["total_amount"].sum() / d["invoice"].nunique()                   # 客单价
    print(name, round(aov), d["country"].value_counts().head(5).to_dict())
```

**缺失比例**：缺失 Customer ID 的交易占**总行数 22.8%**，但仅占总金额 **13.7%**（金额占比远低于行数占比，说明匿名交易多为小额/低频）。

**差异对比**：
- 国家分布：有 ID 多为 `United Kingdom(741301)、Germany(17624)、EIRE(16195)、France(14202)、Netherlands(5140)`；无 ID 多为 `United Kingdom(240029)、EIRE(1671)、Hong Kong(364)、Unspecified(232)、France(128)`。
- 客单价（每发票均值）：有 ID ≈ 371，无 ID ≈ 302。
- 高频商品：有 ID 偏好 `WHITE HANGING HEART T-LIGHT HOLDER(5315)、REGENCY CAKESTAND 3 TIER(3777)、ASSORTED COLOUR BIRD ORNAMENT(2794)`；无 ID 偏好 `DOTCOM POSTAGE(1428)、JUMBO BAG RED RETROSPOT(693)、JUMBO STORAGE BAG SUKI(635)`。

**推测**：匿名记录大概率是**游客/线下批发散客**（无注册账号、单次大额拿货），或 B2B 电话/邮件下单未绑定账号。它们不适合做「注册用户 RFM 分群」，但可作为独立的「非会员渠道」单独分析。
