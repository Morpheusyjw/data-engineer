# Q3 校验报告（validation_report.md）

基准日（数据集最后一天）：2011-11-29

| 输出 | 行数 | 空值率 | 关键指标 |
|------|------|--------|----------|
| sales_facts | 52256 | 0.00% | GMV=236,398,127 |
| customer_features | 7515 | 0.00% | avg_monetary=23,942.2 |
| returns_log | 7572 | 6.80% | unmatched=515 |

## sales_facts 关键分布
- 国家 TOP3：United Kingdom, Belgium, Italy
- 总金额(GMV)：236,398,127

## customer_features 关键分布
- 客户数：7515
- 一次性买家占比：3.15%
- Recency 中位数：124 天

## returns_log 关键分布
- 退货行数：7572
- 匹配成功率：93.20%
