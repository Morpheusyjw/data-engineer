# Q4 准确率评估报告（accuracy_evaluation.md）

## 一、自动结构校验（可复现代理指标）
- 总抽取条数：14447
- 各类别分布：
- other: 7884
- delivery_late: 2902
- quality_defect: 1485
- seller_communication: 1134
- wrong_product: 886
- missing_item: 882
- packaging: 576
- evidence_quote 为空的条目数：6（占比 0.0%）

## 二、防幻觉交叉验证
对 `evidence_quote` 做校验：它必须是原评价文本的**真实子串**。
下方给出一段可复用的校验脚本思路（在 extract_reviews.py 基础上扩展）：
```python
for r in results:
    raw = review_map[r["review_id"]]  # 原始文本
    for iss in r["issues"]:
        assert iss["evidence_quote"] in raw or iss["evidence_quote"] == "", "幻觉证据！"
```
若断言通过，说明抽取未编造原文不存在的句子。

## 三、最终人工校验方法（抽样 30 条）
没有 ground truth 时，采用「人工标注 vs 机器抽取」对齐：
1. 从 14447 条中**分层抽样** 30 条（按 category 比例抽，保证覆盖各类）。
2. 由人工阅读原文，独立标注每个 issue 的 category / severity。
3. 计算：
   - **类别准确率** = 机器 category 与人工一致数 / 30
   - **严重度一致率** = severity 一致数 / 30
   - **证据命中率** = evidence_quote 确实出现在原文的比例
4. 记录分歧样例，回流优化 prompt_template.txt。

> 说明：本环境无人工标注资源，故此处给出的是**评估方法与流程设计**；
> 真实施工时按上述三步抽样即可得出具体数值。规则降级模式下置信度统一 0.5，
> 真实 LLM 模式会返回模型自估 confidence，可作为二次筛选阈值。
