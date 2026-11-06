-- ============================================================
-- Q2.2 平台真实成交分析（按月维度）
-- 注意：order_status 不全是 delivered，必须按状态分别统计。
-- 方言：MySQL 8.0
-- ============================================================

SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')                    AS month,
    COUNT(DISTINCT o.order_id)                                         AS total_orders,
    COUNT(DISTINCT CASE WHEN o.order_status = 'delivered'
                       THEN o.order_id END)                            AS delivered_orders,
    COUNT(DISTINCT CASE WHEN o.order_status = 'canceled'
                       THEN o.order_id END)                            AS canceled_orders,
    -- 取消率：取消 / 总下单，保留 2 位小数
    ROUND(
        COUNT(DISTINCT CASE WHEN o.order_status = 'canceled'
                           THEN o.order_id END)
        / NULLIF(COUNT(DISTINCT o.order_id), 0),
        2)                                                             AS cancel_rate,
    -- 已送达订单 GMV：price + freight_value（不要漏运费）
    SUM(CASE WHEN o.order_status = 'delivered'
             THEN oi.price + oi.freight_value ELSE 0 END)             AS delivered_gmv,
    -- 平均送达天数：仅对「已送达且有送达时间」的订单计算，NULL 不计入
    ROUND(AVG(CASE WHEN o.order_status = 'delivered'
                  AND o.order_delivered_customer_date IS NOT NULL
                  THEN DATEDIFF(o.order_delivered_customer_date,
                               o.order_purchase_timestamp)
             END), 2)                                                 AS avg_delivery_days
FROM olist_orders AS o
LEFT JOIN olist_order_items AS oi
    ON o.order_id = oi.order_id
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')
ORDER BY month;
