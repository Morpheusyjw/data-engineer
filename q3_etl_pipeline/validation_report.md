# Q3 校验报告（validation_report.md）

基准日（数据集最后一天）：2011-12-09

| 输出 | 行数 | 空值率 | 关键指标 |
|------|------|--------|----------|
| sales_facts | 1036876 | 0.00% | GMV=20,108,979 |
| customer_features | 5852 | 0.00% | avg_monetary=2,979.2 |
| returns_log | 19493 | 65.02% | unmatched=12674 |

## sales_facts 关键分布
- 国家 TOP3：United Kingdom, EIRE, Germany
- 总金额(GMV)：20,108,979

## customer_features 关键分布
- 客户数：5852
- 一次性买家占比：27.65%
- Recency 中位数：94 天

## returns_log 关键分布
- 退货行数：19493
- 匹配成功率：34.98%
