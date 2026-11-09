-- ============================================================
-- Q2.2 平台真实成交分析（按月维度）
-- 注意：order_status 不全是 delivered，必须按状态分别统计。
-- 方言：MySQL 8.0
--
-- 关键口径（第一版踩过的坑，见 q2_4_query_optimization.md 末尾）：
--   orders : order_items 是 1:N。直接 JOIN 后 COUNT(DISTINCT order_id) 不会错，
--   但 AVG(DATEDIFF(...)) 会按「商品行数」加权——一个含 5 件商品的订单
--   对平均送达天数的影响是单件订单的 5 倍。所以先把明细聚合到「订单粒度」，
--   再在订单粒度上算平均，这样每月每单权重相同。
-- ============================================================

WITH order_level AS (
    SELECT
        o.order_id,
        DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')      AS month,
        o.order_status,
        o.order_purchase_timestamp,
        o.order_delivered_customer_date,
        -- 订单金额：price + freight_value（不可漏运费），先按订单汇总
        SUM(oi.price + oi.freight_value)                      AS order_gmv
    FROM olist_orders AS o
    LEFT JOIN olist_order_items AS oi
        ON o.order_id = oi.order_id
    GROUP BY
        o.order_id,
        o.order_purchase_timestamp,
        o.order_status,
        o.order_delivered_customer_date
)
SELECT
    month,
    COUNT(*)                                                      AS total_orders,
    SUM(order_status = 'delivered')                                AS delivered_orders,
    SUM(order_status = 'canceled')                                 AS canceled_orders,
    -- 取消率：取消 / 总下单，保留 2 位小数
    ROUND(SUM(order_status = 'canceled') / NULLIF(COUNT(*), 0), 2)  AS cancel_rate,
    -- 已送达订单 GMV：口径 = 订单内所有商品 price + freight_value
    ROUND(SUM(CASE WHEN order_status = 'delivered'
                   THEN order_gmv ELSE 0 END), 2)                  AS delivered_gmv,
    -- 平均送达天数：只对「已送达且有送达时间」的订单取平均；
    -- 未送达 / 无送达时间的订单既不进分子也不进分母（NULL 被 AVG 忽略）
    ROUND(AVG(CASE WHEN order_status = 'delivered'
                    AND order_delivered_customer_date IS NOT NULL
                   THEN DATEDIFF(order_delivered_customer_date,
                                 order_purchase_timestamp)
              END), 2)                                             AS avg_delivery_days
FROM order_level
GROUP BY month
ORDER BY month;
