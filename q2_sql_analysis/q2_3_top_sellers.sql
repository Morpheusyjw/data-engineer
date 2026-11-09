-- ============================================================
-- Q2.3 2017 年 GMV TOP 20 卖家（含州内排名）
-- 评分要点：窗口函数做州内排名 / 评分去重 / 延迟率逻辑 / CTE 可读性
-- 方言：MySQL 8.0
--
-- 三个口径坑（第一版都踩过，结果会静默算错，不报错）：
--   1) orders ⋈ order_items 是 1:N，若直接 AVG(review_score) 会按商品行数加权；
--      -> 先聚合到「卖家 × 订单」粒度，一单一行，再做 AVG。
--   2) olist_orders.customer_id 是「按订单生成的代理键」，一单一个，几乎不复用；
--      直接 COUNT(DISTINCT customer_id) 会恒等于订单数（看第一版结果：243/243）。
--      真正的复购人数要用 olist_customers.customer_unique_id。
--   3) 延迟率的分母只能是「已送达且有送达时间」的订单；把 NULL 当 0 会稀释延迟率。
-- ============================================================

WITH order_gmv AS (
    -- 卖家 × 订单 粒度：一个订单可含多个卖家的商品，先各自汇总金额
    SELECT
        oi.seller_id,
        oi.order_id,
        SUM(oi.price + oi.freight_value) AS order_gmv
    FROM olist_order_items AS oi
    JOIN olist_orders AS o
        ON oi.order_id = o.order_id
    WHERE o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-01-01'
    GROUP BY oi.seller_id, oi.order_id
),
order_attr AS (
    -- 订单级属性（每单一行）+ 真实的客户自然键 customer_unique_id
    SELECT
        o.order_id,
        c.customer_unique_id,
        o.order_status,
        o.order_delivered_customer_date,
        o.order_estimated_delivery_date
    FROM olist_orders AS o
    JOIN olist_customers AS c
        ON o.customer_id = c.customer_id
    WHERE o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-01-01'
),
review_dedup AS (
    -- 评分去重：一个订单可能有多条评价，先按订单取平均
    SELECT order_id, AVG(review_score) AS review_score
    FROM olist_order_reviews
    GROUP BY order_id
),
seller_agg AS (
    SELECT
        og.seller_id,
        SUM(og.order_gmv)                                          AS gmv_2017,
        COUNT(*)                                                   AS order_count,
        COUNT(DISTINCT oa.customer_unique_id)                      AS unique_customers,
        AVG(rv.review_score)                                       AS avg_review_score,
        -- 延迟送达率：仅已送达订单参与；未送达 / 缺时间 → NULL，不参与分母
        AVG(CASE
                WHEN oa.order_delivered_customer_date IS NULL
                  OR oa.order_estimated_delivery_date IS NULL THEN NULL
                WHEN oa.order_delivered_customer_date
                     > oa.order_estimated_delivery_date          THEN 1.0
                ELSE 0.0
            END)                                                   AS late_delivery_rate,
        AVG(CASE WHEN oa.order_status = 'canceled' THEN 1.0 ELSE 0.0 END) AS cancel_rate
    FROM order_gmv AS og
    JOIN order_attr AS oa
        ON og.order_id = oa.order_id
    LEFT JOIN review_dedup AS rv
        ON og.order_id = rv.order_id
    GROUP BY og.seller_id
),
seller_with_state AS (
    SELECT sa.*, s.seller_state
    FROM seller_agg AS sa
    JOIN olist_sellers AS s
        ON sa.seller_id = s.seller_id
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
    ROUND(gmv_2017, 2)           AS gmv_2017,
    order_count,
    unique_customers,
    ROUND(avg_review_score, 3)   AS avg_review_score,
    ROUND(late_delivery_rate, 4) AS late_delivery_rate,
    ROUND(cancel_rate, 4)        AS cancel_rate,
    state_rank
FROM ranked
ORDER BY gmv_2017 DESC
LIMIT 20;
