# Q3 校验报告（validation_report.md）

基准日（数据集最后一天）：2010-12-27

| 输出 | 行数 | 空值率 | 关键指标 |
|------|------|--------|----------|
| sales_facts | 2966 | 0.00% | GMV=1,020,873 |
| customer_features | 1850 | 0.00% | avg_monetary=395.7 |
| returns_log | 484 | 89.46% | unmatched=433 |

## sales_facts 关键分布
- 国家 TOP3：United Kingdom, Germany, France
- 总金额(GMV)：1,020,873

## customer_features 关键分布
- 客户数：1850
- 一次性买家占比：81.73%
- Recency 中位数：164 天

## returns_log 关键分布
- 退货行数：484
- 匹配成功率：10.54%
