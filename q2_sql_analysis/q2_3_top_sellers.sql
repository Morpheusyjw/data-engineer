-- ============================================================
-- Q2.3 2017 年 GMV TOP 20 卖家（含州内排名）
-- 评分要点：窗口函数做州内排名 / 评分去重 / 延迟率逻辑 / CTE 可读性
-- 方言：MySQL 8.0
-- ============================================================

WITH seller_items AS (
    -- 卖家在 2017 年卖出的每个订单的金额
    SELECT
        oi.seller_id,
        oi.order_id,
        (oi.price + oi.freight_value) AS item_gmv
    FROM olist_order_items AS oi
    JOIN olist_orders AS o
        ON oi.order_id = o.order_id
    WHERE o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-01-01'
),
order_attr AS (
    -- 订单级属性（每个订单一行，避免后续被 items 行放大）
    SELECT
        order_id,
        customer_id,
        order_status,
        order_delivered_customer_date,
        order_estimated_delivery_date
    FROM olist_orders
    WHERE order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-01-01'
),
review_dedup AS (
    -- 评分去重：一个订单可能多条评价，先按订单取平均
    SELECT order_id, AVG(review_score) AS review_score
    FROM olist_order_reviews
    GROUP BY order_id
),
seller_agg AS (
    SELECT
        si.seller_id,
        SUM(si.item_gmv)                                              AS gmv_2017,
        COUNT(DISTINCT si.order_id)                                   AS order_count,
        COUNT(DISTINCT oa.customer_id)                                AS unique_customers,
        AVG(rv.review_score)                                          AS avg_review_score,
        AVG(CASE WHEN oa.order_delivered_customer_date
                     > oa.order_estimated_delivery_date
                THEN 1.0 ELSE 0.0 END)                               AS late_delivery_rate,
        AVG(CASE WHEN oa.order_status = 'canceled'
                THEN 1.0 ELSE 0.0 END)                               AS cancel_rate
    FROM seller_items AS si
    JOIN order_attr   AS oa ON si.order_id = oa.order_id
    LEFT JOIN review_dedup AS rv ON si.order_id = rv.order_id
    GROUP BY si.seller_id
),
seller_with_state AS (
    SELECT sa.*, s.seller_state
    FROM seller_agg AS sa
    JOIN olist_sellers AS s ON sa.seller_id = s.seller_id
),
ranked AS (
    -- 州内按 GMV 排名
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY seller_state
            ORDER BY gmv_2017 DESC
        ) AS state_rank
    FROM seller_with_state
)
-- 全局 TOP 20（保留各自的州内排名 state_rank）
SELECT
    seller_id,
    seller_state,
    ROUND(gmv_2017, 2)        AS gmv_2017,
    order_count,
    unique_customers,
    ROUND(avg_review_score, 3) AS avg_review_score,
    ROUND(late_delivery_rate, 4) AS late_delivery_rate,
    ROUND(cancel_rate, 4)       AS cancel_rate,
    state_rank
FROM ranked
ORDER BY gmv_2017 DESC
LIMIT 20;
