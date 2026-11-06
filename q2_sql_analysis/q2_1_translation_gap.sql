-- ============================================================
-- Q2.1 商品类别翻译完整性
-- 找出 products 中存在、但翻译表没有英文对照的类别，并统计商品数。
-- 方言：MySQL 8.0（使用 LEFT JOIN + IS NULL 反连接）
-- ============================================================

SELECT
    p.product_category_name,
    COUNT(*) AS product_count
FROM olist_products AS p
LEFT JOIN product_category_name_translation AS t
    ON p.product_category_name = t.product_category_name
WHERE t.product_category_name IS NULL          -- 翻译表没有匹配 → 缺失翻译
  AND p.product_category_name IS NOT NULL       -- 排除产品表自身为空的类别
GROUP BY p.product_category_name
ORDER BY product_count DESC;

-- ------------------------------------------------------------
-- 进阶：缺失翻译的 3 种处理方案（利弊）
-- ------------------------------------------------------------
-- 方案 A：保留葡萄牙语原名进入下游 BI，在展示层按语言切换
--   利：零数据损失，业务可读；弊：英文看板/国际化报表仍缺失。
-- 方案 B：用通用翻译 API（如 Google/DeepL）批量补全，写回翻译表
--   利：自动化、可规模化；弊：API 有成本，且长尾类别翻译质量参差需人工抽检。
-- 方案 C：将缺失类别统一归为 'unknown' / 'other' 单独桶
--   利：简单、避免脏数据扩散；弊：丢失细分信息，影响品类分析精度。
-- 推荐：A + B 结合——先保留原名，再用 API 补全高频缺失类，低频类置 other。
