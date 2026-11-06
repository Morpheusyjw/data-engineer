# 数据工程师笔试 · 候选人提交

> 候选人：[你的名字]　|　岗位：数据工程师（校招/社招）　|　提交日期：2026-11-11
> 技术栈：Python 3.12 · pandas · MySQL 8.0 · SQLAlchemy · OpenAI API · Docker
> 原题仓库：[Jay-gekko/data-engineer](https://github.com/Jay-gekko/data-engineer)（已 Fork 到本人公开仓库）

## 一、项目总览

本项目按原题五大模块 + 加分题完整实现，所有代码注释与文档均为中文：

| 模块 | 目录 | 交付物 |
|------|------|--------|
| Q1 数据质量探索 | `q1_data_quality/` | `data_quality_report.md` / `findings.md` / `cleaning_strategy.md` |
| Q2 SQL 分析 | `q2_sql_analysis/` | 3 段 `.sql` + `q2_4` 优化分析 + `run_q2.py`（灌库脚本） |
| Q3 ETL 管道 | `q3_etl_pipeline/` | `pipeline.py` + 3 个 `.parquet` + `pipeline_log.txt` + `validation_report.md` |
| Q4 LLM 抽取 | `q4_llm_extraction/` | `extract_reviews.py` + `prompt_template.txt` + 各类报告 |
| Q5 系统设计 | `q5_system_design/` | `real_time_pipeline_design.md`（含架构图） |
| 加分题 | `bonus/` | `q6_1_ai_collaboration.md` / `q6_2_business_insights.md` |

**三份必填文档**：[`REFLECTION.md`](REFLECTION.md)（反思）· [`TOOLS.md`](TOOLS.md)（工具清单）· [`AI_LOG.md`](AI_LOG.md)（AI 对话记录）

## 二、如何一键运行

```bash
# 1) 按 SETUP.md 配好环境（Python3.12 虚拟环境 + 依赖 + Kaggle token + MySQL8 + 可选 LLM Key）
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) 一键跑通（含数据下载 → 各模块依次执行，单模块失败不阻塞其余）
python run_all.py

# 仅跑部分模块调试：
python run_all.py --only q1 q3
```

`run_all.py` 用 `try/except` 隔离每个模块：缺 Kaggle 数据 / 没起 MySQL / 没填 LLM Key 都不会让整条链路崩，
而是记录原因继续（Q4 还会自动降级为规则方法）。详细环境步骤见 [`SETUP.md`](SETUP.md)。

## 三、数据说明

两份 Kaggle 数据集**不随仓库提交**（`.gitignore` 已忽略 `data/*.csv`、`outputs/*.parquet` 等）。
运行 `python run_all.py` 时由 `download_data.py` 自动下载到 `data/`；也可按 `SETUP.md` 手动放置。

## 四、亮点（面试可追问）

- Q1 主动做了**列名归一化**层（`common/dataset_io.py`），应对不同平台列名不一致的真实坑。
- Q3 退货匹配用**字典索引 + 仅退货子集循环**避免全表笛卡尔爆炸，并写了断言与日志。
- Q2.4 指出原慢查询的**隐藏统计错误**（`SUM(price)` 因多表 JOIN 行膨胀而虚高）。
- Q4 两级分流 + 批量 + 防幻觉（evidence 必须原文子串），无 Key 也能跑通。
- Q5 给出 **10 万/天 vs 100 万/天不同架构**的 LLM 成本量化与 3 大风险预案。

> 诚实声明：代码全程借助 AI 辅助完成，但在 `REFLECTION.md` 中已逐题标注「我自己的思路」与「尚未完全吃透之处」。

## 五、如何提交（Fork → 推送）

本项目已在本地完成 **9 个独立 commit（每个模块一个，信息明确）**。请把仓库 **Fork 到你的公开 GitHub 仓库**后推送，
并附上最终 commit hash。完整分步命令（含 rebase 冲突处理、发邮件模板）见 ➜ **[`SUBMIT.md`](SUBMIT.md)**。

> ⚠️ 严禁把数据集 CSV / `.env` 提交（`.gitignore` 已忽略）。提交后**不要再改代码**，hash 会变。
