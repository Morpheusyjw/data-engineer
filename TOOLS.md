# TOOLS.md —— 工具与软件使用清单

> 说明：本笔试允许并鼓励使用 AI 与各类工具。以下为本项目实际用到的工具、
> 各自解决的问题、使用场景/关键步骤，以及「不用它时的替代方案」。
> 所有工具链均可在 macOS 上从零搭建，详见 `SETUP.md`。

---

## Python 3.12 + venv
- 解决了什么问题：提供统一、隔离的运行环境，避免系统旧 Python（macOS 自带 3.9）与依赖冲突。
- 使用场景：`brew install python@3.12` 后 `python3.12 -m venv .venv && source .venv/bin/activate`。
- 替代方案：用 `pyenv` 管理多版本；或 Conda。团队若统一用 3.10+ 镜像则直接用镜像。

## pandas / numpy
- 解决了什么问题：Q1 数据质量探索、Q3 ETL 的数据加载、清洗、聚合、Parquet 写出。
- 使用场景：`pd.read_csv` 加载、`groupby` 聚合 RFM、`to_parquet` 落盘。本项目所有数值与表格处理核心。
- 替代方案：纯 Python + csv 模块（太慢，100 万行不可行）；Spark（数据量更大时再上）。

## pyarrow
- 解决了什么问题：高效读写 Parquet（Q3 三个输出格式要求）。
- 使用场景：`df.to_parquet(...)`，列式存储、体积小、被 Spark/DuckDB 等直接读取。
- 替代方案：CSV（但题目明确要求 parquet）；feather（更快但生态窄）。

## SQLAlchemy + PyMySQL
- 解决了什么问题：Q2 把 Olist 9 张 CSV 灌入 MySQL 8.0，并支持用 Python 执行 .sql 取结果。
- 使用场景：`create_engine("mysql+pymysql://...")` → `df.to_sql(...)` 灌库；`pd.read_sql(text(sql), eng)` 取分析结论。
- 替代方案：用 `mysql` CLI 手动 `LOAD DATA INFILE`（更底层、繁琐）；或用 DBeaver 图形化导入。

## MySQL 8.0（Docker）
- 解决了什么问题：完成 Q2 所有 SQL 查询（本试卷强制要求，对齐团队生产数据库，禁用 SQLite）。
- 使用场景：`docker run -d --name mysql8 -e MYSQL_ROOT_PASSWORD=root -p 3306:3306 mysql:8` 起库；
  用 `run_q2.py` 把 9 张 CSV 灌进 `olist` 库，再执行各 `.sql`。
- 替代方案：无（强制要求）。本机直接 `brew install mysql` 也行，但 Docker 最干净、易销毁重来。

## kagglehub（Kaggle Python 包）
- 解决了什么问题：实现 `python run_all.py` 从 0 到 1 自动下载两份数据集，无需手动操作。
- 使用场景：`import kagglehub; kagglehub.dataset_download("mashlyn/online-retail-ii-uci")`，
  配合 `download_data.py` 把文件归一化重命名到 `data/`。需 `~/.kaggle/kaggle.json` 凭证。
- 替代方案：手动去 Kaggle 网页下载 CSV 解压到 `data/`（无凭证时的兜底，SETUP.md 第 5 步）。

## OpenAI API（gpt-4o-mini）
- 解决了什么问题：Q4 对葡萄牙语差评做结构化抽取（category/severity/证据/翻译/情感）。
- 使用场景：`.env` 配置 `OPENAI_API_KEY`；`extract_reviews.py` 批量调用、统计 token 成本、写 `cost_report.md`。
- 替代方案：Anthropic/本地大模型（改 `OPENAI_BASE_URL` 即可兼容）；无 Key 时自动降级为**规则方法**仍出结果。

## python-dotenv
- 解决了什么问题：把 API Key、DB 密码等敏感配置从代码剥离，避免硬编码与误提交。
- 使用场景：项目根放 `.env`（从 `.env.example` 复制），代码 `load_dotenv()` 读取；`.env` 不入库。
- 替代方案：环境变量 export；或 secrets manager（生产级）。

## Git + GitHub（Fork 工作流）
- 解决了什么问题：按要求 Fork 公开仓库、每个模块单独 commit、保留迭代历史供面试官审阅。
- 使用场景：Fork `Jay-gekko/data-engineer` → 克隆 → 按模块 `git add`/`commit`（语义化 message）→ 推送。
- 替代方案：无（提交规范强制）。切勿 force push，否则覆盖迭代历史。

## VS Code
- 解决了什么问题：查看/编辑大量 Python 与 Markdown，调试、运行集成终端。
- 使用场景：`code .` 打开项目，装 Python 插件获得补全与 lint。
- 替代方案：PyCharm；或纯终端 + vim（进阶）。

## tqdm
- 解决了什么问题：Q3/Q4 大批量处理时提供进度可视化，避免长时间无输出误以为卡死。
- 使用场景：循环处理退货匹配/评价抽取时包裹迭代器显示进度。
- 替代方案：print 日志；或不用（逻辑上非必需）。

## Docker Desktop
- 解决了什么问题：在本机隔离运行 MySQL 8.0，不污染宿主机环境，一键启停。
- 使用场景：安装后在终端 `docker run ... mysql:8`；`docker ps` 查看状态。
- 替代方案：本机直装 MySQL；或远程/云数据库（需网络与费用）。
