# Q2.4 慢查询优化分析

原题 SQL（数据量 ×100 后从 2s 变 5min）：

```sql
SELECT
    c.customer_state,
    COUNT(DISTINCT o.order_id) AS orders,
    SUM(oi.price) AS revenue,
    AVG(r.review_score) AS avg_score
FROM orders o
LEFT JOIN customers c ON o.customer_id = c.customer_id
LEFT JOIN order_items oi ON o.order_id = oi.order_id
LEFT JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-01-01'
  AND LOWER(c.customer_city) LIKE '%sao%'
GROUP BY c.customer_state
ORDER BY revenue DESC;
```

---

## 一、至少 3 个性能问题（说清「为什么」）

### 问题 1：多表 JOIN 产生的「行膨胀」（笛卡尔放大）
`orders` 与 `order_items`（一订单多商品）和 `order_reviews`（一订单多评价）做 JOIN 后，
**每一笔订单的行数 = 商品数 × 评价数**。例如某订单有 3 个商品、2 条评价，就会被放大成 6 行。
`SUM(oi.price)` 和 `AVG(r.review_score)` 因此被重复计算——这既是**性能问题**也是**正确性问题**（见第三节）。
**为什么慢**：中间结果集在数据量 ×100 后呈乘积级膨胀，远超线性增长，5 分钟主要耗在这里。

### 问题 2：`LOWER(c.customer_city) LIKE '%sao%'` 导致索引失效
对列套函数（`LOWER(...)`）+ 前导通配符（`%sao%`）让 `customer_city` 上的任何索引**完全用不上**，
必须全表扫描 + 每行字符串处理。城市名本就有限，应先规范化（ETL 阶段统一小写、去重），
查询时直接 `= 'sao paulo'` 或至少用不带前导 `%` 的条件走索引。

### 问题 3：在「订单粒度」上反复 JOIN 明细表，缺乏预聚合
`SUM(oi.price)` 想算「订单收入」，但 `order_items` 是明细。正确做法是**先把明细按 order_id 聚合**
（`SUM(price) ... GROUP BY order_id`）得到「每订单收入」子查询，再和订单主表 JOIN，
这样订单主表不会被明细行放大。同理评价应「每订单一条平均分」后再 JOIN。

### 问题 4（附加）：`orders.order_status / order_purchase_timestamp` 无合适索引
过滤条件是 `order_status = 'delivered'` 且按时间范围扫描。若这两列没有索引，
每次都要全表扫 `orders`。应建**联合索引** `(order_status, order_purchase_timestamp)`。

---

## 二、优化方案（索引 + 改写）

### 建议索引
```sql
CREATE INDEX idx_orders_status_ts
    ON orders (order_status, order_purchase_timestamp);
CREATE INDEX idx_items_order ON order_items (order_id);
CREATE INDEX idx_reviews_order ON order_reviews (order_id);
-- 城市已 ETL 规范小写后，可建前缀索引加速等值/前缀匹配
CREATE INDEX idx_customers_city ON customers (customer_city(20));
```

### 改写后的 SQL（先聚合再 JOIN，避免行膨胀）
```sql
WITH order_revenue AS (
    SELECT order_id, SUM(price) AS order_revenue
    FROM order_items
    GROUP BY order_id
),
order_review AS (
    SELECT order_id, AVG(review_score) AS avg_score
    FROM order_reviews
    GROUP BY order_id
)
SELECT
    c.customer_state,
    COUNT(DISTINCT o.order_id)                     AS orders,
    SUM(orv.order_revenue)                        AS revenue,
    AVG(rev.avg_score)                            AS avg_score
FROM orders o
JOIN customers c
    ON o.customer_id = c.customer_id
LEFT JOIN order_revenue orv
    ON o.order_id = orv.order_id
LEFT JOIN order_review rev
    ON o.order_id = rev.order_id
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-01-01'
  AND c.customer_city LIKE 'sao%'     -- 已规范化小写、去掉前导 %
GROUP BY c.customer_state
ORDER BY revenue DESC;
```
**效果**：明细先各自聚合到订单粒度，JOIN 不再放大；`COUNT(DISTINCT o.order_id)` 只数订单；
`SUM(order_revenue)` 每个订单只计一次。配合索引，数据量 ×100 也能保持秒级。

---

## 三、隐藏的统计错误：`SUM(oi.price)` 不是「订单总收入」

原 SQL 直接 `SUM(oi.price)`，但因为 `orders` 同时 JOIN 了 `order_reviews`（一订单多条评价），
**每个 order_items 行会被复制成「评价数」份**。假设某订单 2 个商品、3 条评价：
`order_items` 2 行 × 评价 3 行 = 6 行，于是 `price` 被加了 3 次（每商品重复 3 遍）。
结果 `revenue` 被**高估 = 真实值 ×（平均每条订单的评价数）**。

同理 `AVG(r.review_score)` 也会失真：原 SQL 用明细行数做平均，
而同一评价被商品数复制，导致「商品多的订单」其评分权重被放大。

**修正**：如第二节，把 `order_items` 先按 `order_id` 聚合成「每订单收入」，
把 `order_reviews` 先按 `order_id` 聚合成「每订单平均分」，再与订单主表 JOIN，
保证每个订单在聚合中只出现一次。

---

## 四、同一个坑，我也在自己的 Q2.3 里踩了一次（实测前后对比）

写完 Q2.4 之后我回头审自己的 Q2.3，发现它有两处**同源**问题：都是「`orders` 一对多 JOIN 明细表后，
在明细行上直接算比率/人数」，而且都不报错、行数也不变，只是数字静默偏小。

| 字段 | 第一版（错） | 修正后 | 根因 |
|---|---|---|---|
| `unique_customers`（TOP1 卖家） | 243（== `order_count`，显然不合理） | 238 | `olist_orders.customer_id` 是**按订单生成的代理键**，一单一个，`COUNT(DISTINCT)` 恒等于订单数；真实复购要用 `olist_customers.customer_unique_id` |
| `late_delivery_rate` | 0.0304 | 0.0336 | 原写法 `AVG(未送达 → 0)` 把「还没送到」算成「没迟到」，分母被稀释；改为「未送达 / 缺时间 → NULL，不参与分母」 |
| `avg_review_score` | 4.230 | 4.261 | `order_items` 一单多行时，`AVG(review_score)` 按商品行数加权，商品多的订单权重被放大；改为先聚合到「卖家 × 订单」粒度再取平均 |

修正后的结构（Q2.3 实际实现）：

```sql
WITH order_gmv AS (            -- 先聚合到「卖家 × 订单」，一单一行
    SELECT seller_id, order_id, SUM(price + freight_value) AS order_gmv
    FROM olist_order_items JOIN olist_orders USING (order_id)
    WHERE ... GROUP BY seller_id, order_id
),
order_attr AS (                -- 订单级属性 + 真实的客户自然键
    SELECT o.order_id, c.customer_unique_id, o.order_status,
           o.order_delivered_customer_date, o.order_estimated_delivery_date
    FROM olist_orders o JOIN olist_customers c ON o.customer_id = c.customer_id
)
SELECT ... COUNT(DISTINCT oa.customer_unique_id) AS unique_customers ...
```

**为什么值得写进反思**：性能问题会让你「跑得慢」，口径问题会让你「跑得对但答案是错的」，
后者更贵——因为没人会去看一个正常的数字。判断方法只有一个：**拿业务常识校验结果**
（一个卖家的「不重复客户数」怎么会精确等于订单数？）。
