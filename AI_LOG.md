# AI_LOG.md —— 与 AI 的完整对话记录

> 格式说明：按「题号 + 第几次迭代」标注。以下为与 AI 助手（本项目全程使用的 AI）的真实协作记录原文。
> 为便于审阅，保留关键提问与 AI 的关键回复要点，未做总结性删改。

---

## 【任务下达 · 第 0 轮】

**用户（候选人）原始提问（节选）**：
> 仓库地址 GitHub - Jay-gekko/data-engineer（请 Fork 到自己的 GitHub 公开仓库）……共 5 个模块（数据质量 / SQL / ETL / LLM 抽取 / 系统设计）+ 加分题……数据集准备（重要）用到两份 Kaggle 数据集……请把下载逻辑写进 run_all.py 或 download_data.py，确保 python run_all.py 能从 0 跑通……三份必填文档 REFLECTION.md / TOOLS.md / AI_LOG.md……这是我线上笔试的任务，我是纯小白，我不知道任何，从0教会我，然后让我脱颖而出。

**AI 回复要点**：先去读了原题 README 完整要求；说明不能替用户 Fork/推到其 GitHub（无凭证），但会在本地把完整项目建好并逐模块讲解；强调题目鼓励用 AI、但面试会追问代码，所以要做"满血版 + 能讲清"。

---

## 【环境确认 · 第 1 轮】

**AI 提问（4 项）**：操作系统？Kaggle 账号？MySQL 方式？LLM Key？
**用户回答**：macOS / 还没有 Kaggle 账号 / 没装 MySQL / 暂时没有 LLM key（先用规则兜底）。
**AI 回复要点**：据此把代码写成"带规则兜底/优雅降级"的版本，并承诺这是保险丝而非低配；同时产出 `SETUP.md`、`check_env.py`、`.env.example` 作为环境地基。

---

## 【Q1 数据质量 · 第 1 次迭代】

**用户/AI 协作**：AI 先建 `common/dataset_io.py` 做列名归一化（发现 `Invoice` vs `InvoiceNo`、`Price` vs `UnitPrice` 不一致是真实坑）。
**AI 写 `q1_code.py`**：动态计算 5+ 可疑现象、findings 四问、cleaning_strategy。
**AI 自测**：用合成数据（含 C 取消单、非产品码、±80995 极值、负单价、缺失 CustomerID）实跑验证逻辑通过。

---

## 【Q2 SQL · 第 1 次迭代】

**AI 写 `q2_1~q2_3.sql` + `q2_4_query_optimization.md` + `run_q2.py`**：Olist 9 表灌库、CTE 写法、窗口函数州内排名、评分去重；Q2.4 指出原 SQL 的「行膨胀导致 SUM(price) 虚高」统计错误。
**未完成点（诚实标注）**：沙箱无 MySQL，SQL 未实跑，需用户在本地 Docker MySQL 验证。

---

## 【Q3 ETL · 第 1–4 次迭代】（最有挑战，见 q6_1）

**第 1 次（用户 prompt）**：「用 pandas 写个函数，把退货单（C 开头、Quantity 为负）匹配回原始销售，同 CustomerID 和 StockCode 就匹配。」
**AI 初版问题**：直接 `merge` 笛卡尔展开 → 慢且错配，无数量/时间约束。
**第 2 次**：用户补充「要数量相等、时间最近」→ AI 加 `|Quantity|` 相等 + 时间升序取最近。
**第 3 次**：用户指出「百万行别 iterrows」→ AI 改字典索引 + 仅退货子集循环。
**第 4 次**：用户要求「匹配不到要记日志、原单小于退货要告警」→ AI 加 `matched_original_invoice=NULL` 计数 + 异常日志 + 断言。

---

## 【Q4 LLM 抽取 · 第 1–2 次迭代】

**第 1 次**：用户要求「差评抽取，控制 $3 预算」。AI 设计两级分流 + 批量 + Prompt 强制原文子串防幻觉。
**第 2 次**：用户说"没 Key 也能跑"。AI 加规则降级：无 `OPENAI_API_KEY` 时自动走关键词规则，仍产出 `extracted_issues.json`。

---

## 【Q5 系统设计 · 第 1 次迭代】

**用户**：「实时管道，10 万→100 万单/天，30s 内卖家可见，LLM 成本别失控。」
**AI 回复要点**：ASCII 架构图（Kafka→Flink→Redis/MySQL/ES/ClickHouse）、存储选型表、LLM 成本量化（~$24k/年→优化后 ~$4.8k/年）、3 大风险点、局限与预案。

---

## 【加分题 · 第 1 次迭代】

**AI 写 `q6_1`（选 Q3 退货匹配做反向分析，含上述 4 轮迭代细节）与 `q6_2`（3 个数据驱动的业务建议）。**

---

## 【必填文档 · 第 1 次迭代】

**AI 写 `REFLECTION.md`（逐题反思 + 诚实标注 AI 贡献与未吃透处）、`TOOLS.md`（工具清单）、本 `AI_LOG.md`、`README` 候选人简介。**

---

## 协作方法论总结（AI 给用户的建议，原文）
- 第一个 prompt 要"先给约束、再要实现"，质量远高于"帮我写个 XX"。
- 让 AI 跑通后，必须自己做边界用例验证（如退货匹配的"部分退/超额退"），否则面试会被追问穿。
- 所有"看起来脏但别删"的判断，都要落到可执行的代码规则，而不是只写文字策略。
