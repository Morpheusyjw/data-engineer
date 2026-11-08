# TOOLS.md - 工具与软件使用清单

> 请列出本次笔试中**所有使用过的软件、工具、库**。
> 📌 **填写要求**：每个工具至少写明三件事：解决什么问题、使用场景、替代方案；不要为了凑数列出 `os`、`sys` 这种标准库；重点列那些**对你解题有实质帮助**的工具；不熟悉的工具不要硬列 —— 面试会追问。

---

## 🤖 AI 工具

### 工具 1：WorkBuddy（内置 AI 编程助手）

- **版本/型号**：WorkBuddy 内置 AI 助手（本环境）
- **解决了什么问题**：从 0 搭建整个笔试项目——环境探测、写 5 个模块代码、Debug（MySQL 认证、建库顺序、BOM、退货匹配）、生成三份必交文档。
- **使用场景**：每道题先给约束再要实现；跑通后由我（候选人）做边界用例验证，再让 AI 修正。
- **替代方案**：Claude / ChatGPT + GitHub Copilot / Cursor（效果类似，但需自行管理上下文）。

---

## 💻 IDE / 开发环境

### 工具 1：WorkBuddy 内置编辑器 / 终端

- **解决了什么问题**：在同一环境内编辑 Python/Markdown、运行集成终端、查看产物，避免多工具切换。
- **使用场景**：`code .` 等价物打开项目，装 Python 插件获得补全与 lint。
- **替代方案**：VS Code（装 Python 插件）；PyCharm；纯终端 + vim（进阶）。

---

## 🐍 Python 库

### 数据处理

| 库 | 版本 | 用途 | 替代方案 |
|----|------|------|----------|
| pandas | 3.1.1 | Q1 数据质量、Q3 ETL 的加载/清洗/聚合/Parquet 写出（核心） | 纯 Python+csv（百万行太慢）；Spark（更大规模） |
| numpy | 2.5.4 | 向量化数值计算 | 纯 Python（慢） |
| pyarrow | 26.0.1 | 高效读写 Parquet（Q3 三个输出格式要求） | CSV（题目明确要求 parquet）；feather |

### 数据库 / SQL（强制使用 MySQL 8.0+）

| 库 | 版本 | 用途 | 替代方案 |
|----|------|------|----------|
| pymysql | 1.2.3 | MySQL 8 驱动，Python 侧建连 | mysqlclient（需编译） |
| sqlalchemy | 2.1.8 | 用 `to_sql` 把 9 张 CSV 灌入 olist 库；`read_sql` 取分析结果 | 直接用 pymysql cursor 手写 |
| cryptography | （未直接安装） | 说明：模板建议用于 `caching_sha2_password` 认证；本项目改用 `mysql_native_password`（见下反思），故未引入该依赖 | — |

### LLM / API

| 库 | 版本 | 用途 | 替代方案 |
|----|------|------|----------|
| openai | 3.46.0 | Q4 调用 LLM（OpenAI 兼容端点，含本地 Ollama）做差评结构化抽取 | anthropic；本地 llama.cpp |
| kagglehub | 1.0.3 | 实现 `python run_all.py` 从 0 自动下载 Online Retail II（免 Kaggle 账号） | 手动网页下载 CSV；Kaggle CLI |
| python-dotenv | 1.2.4 | 把 DB 密码/Key 从代码剥离到 `.env`（不入库） | 环境变量 export；secrets manager |
| tabulate | 0.10.0 | Q2 结果转 Markdown 表格报告 | 手拼字符串 |
| tqdm | 4.70.1 | Q3/Q4 大批量处理进度可视化 | print 日志 |

---

## 🛠️ 数据库工具

### 工具 1：MySQL 8.0.46（官网 DMG 本地安装）

- **解决了什么问题**：完成 Q2 所有 SQL 查询（本试卷强制要求，对齐团队生产数据库，禁用 SQLite）。
- **使用场景**：官网下载 DMG 安装并启动为本地服务；`run_q2.py` 把 9 张 CSV 灌进 `olist` 库，再执行各 `.sql` 取分析结论。
- **替代方案**：Docker `mysql:8`（最干净易销毁）；云数据库（需网络与费用）。本项目因本机已装官方版，直接复用。

---

## 🔍 调试与分析工具

> 比如 line_profiler、memory_profiler、pytest 等

- **pandas / SQL `EXPLAIN`**：定位 Q2.4 的 JOIN 行膨胀、验证索引效果。
- **tqdm + 断言（`assert`）**：Q3 跑批时看进度，用 `validate_output()` 断言抓出"演示数据退货命中 0%"的 bug。
- **`utf-8-sig` 读 CSV**：调试 Q2 翻译表列名错乱（BOM 问题）的关键。

---

## 🌐 在线资源 / 文档

> 不需要列出每一次搜索，只列那些对你帮助最大的资源

- **Pandas 官方文档**：查 `merge_asof` / `groupby` 精确语义（Q1/Q3）。
- **MySQL 8.0 Reference Manual**：窗口函数 `ROW_NUMBER()`、`DATE_FORMAT`、执行计划语义（Q2）。
- **Olist 数据集 Kaggle 页**：理解 9 张表关系与字段含义。
- **GitHub 公开镜像**（mohamedyounis10/Olist-brazilian-ecommerce-analytics）：在沙箱无法登录 Kaggle 时，作为 Olist 9 表的可信下载源。

---

## 📌 关键工具决策反思

### 你做过的最重要的工具选型决策是？为什么？
**MySQL 认证插件选型**：本机 MySQL 8 默认 `caching_sha2_password`，pymysql 非加密 TCP 连会握手挂起。我**放弃**让它兼容 sha2（需改服务器端公钥/引入 cryptography），改为把 `root@localhost` 切到 `mysql_native_password`——密码不变、客户端零改动即可直连。这是一个"不在客户端硬刚、改服务端一处"的判断，也是面试常考点。

### 你尝试过但**放弃**的工具/方案？
- **Docker 起 MySQL**：本机已有官方 DMG 版且已跑着，没必要再起容器，省去端口/数据卷折腾。
- **UCI `ucimlrepo` 取 Online Retail II**：实测该库报 "not available for import"，放弃，改用 `kagglehub` 匿名下载成功。

### 如果再做一次，你会换用什么工具？
- Q4 实际接入了 **硅基流动 SiliconFlow（OpenAI 兼容 API）+ Qwen/Qwen2.5-7B-Instruct** 跑真实 LLM（沙箱无法装本地 Ollama，但第三方兼容端点可直连）；用 `Q4_LLM_LIMIT=150` 抽样实跑、其余走规则兜底。代码同时支持本地 Ollama 自动探测（零 Key）与任意 OpenAI 兼容端点。
