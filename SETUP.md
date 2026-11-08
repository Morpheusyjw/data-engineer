# SETUP.md —— 小白环境搭建手册（macOS 专属）

> 目标：把你这台 Mac 配成「能一键跑通 `python run_all.py`」的开发环境。
> 适用：完全从零开始、没装过任何开发工具的同学。
> 原则：**每一步都有「做什么 / 为什么 / 怎么验证」**，复制命令即可，不用理解全部底层原理。

---

## 0. 总览：你要准备 7 样东西（按顺序做）

| # | 要装/申请的东西 | 用途 | 预计耗时 |
|---|----------------|------|---------|
| 1 | Homebrew | macOS 的「软件管家」，后面装什么都靠它 | 3 分钟 |
| 2 | Python 3.12 + 虚拟环境 | 运行所有 Python 代码（题目要 3.10+） | 5 分钟 |
| 3 | Git + GitHub 账号 + Fork 仓库 | 提交代码、按模块 commit、最终交作业 | 10 分钟 |
| 4 | 代码编辑器 VS Code | 看代码、改代码（可选但强烈推荐） | 3 分钟 |
| 5 | Kaggle 账号 + API Token | 下载两份数据集（题目强制，必须从 Kaggle 下） | 5 分钟 |
| 6 | MySQL 8.0（用 Docker 起） | Q2 强制要求，SQL 必须跑在 MySQL 8.0+ | 10 分钟 |
| 7 | LLM API Key（OpenAI） | Q4 调大模型抽取差评（预算 $3，可选但推荐） | 5 分钟 |

> ✅ **先做 1→3→5→6**（这是跑通代码的硬门槛），4 和 7 可以稍后补。
> 每做完一步，可以跑 `python check_env.py` 看哪些灯变绿了。

---

## 1. 安装 Homebrew（软件管家）

打开「终端」（按 `Command + 空格`，输入 `终端` 回车），粘贴下面整段执行：

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

中途会让你输入开机密码，输入时屏幕**不显示字符**，输完回车即可。装完按提示把 brew 加到环境变量（通常它会自动提示你运行两行命令）。

**验证**：
```bash
brew --version
```
能打印出版本号（如 `Homebrew 4.x`）就成功。

---

## 2. 安装 Python 3.12 并建虚拟环境

macOS 自带 Python 太旧（3.9），题目要 3.10+，我们用 Homebrew 装一个新版本：

```bash
brew install python@3.12
```

装好后，进入项目目录并创建「虚拟环境」（相当于给这个项目单独准备一套依赖，互不干扰）：

```bash
cd ~/你的路径/data-engineer      # 换成你放本项目文件夹的位置
python3.12 -m venv .venv
source .venv/bin/activate        # 激活环境（以后每次打开终端都要先执行这行）
```

激活后，命令行最前面会出现 `(.venv)` 字样，表示环境已生效。

**验证**：
```bash
python --version     # 应显示 Python 3.12.x
which python         # 应指向 .venv 目录下的 python
```

> 💡 之后所有 `python` / `pip` 命令都请在 `(.venv)` 激活状态下执行。

---

## 3. Git、GitHub 账号与 Fork 仓库

### 3.1 装 Git
```bash
brew install git
git --version        # 能看到版本即成功
```

### 3.2 注册 GitHub 并配置身份
1. 打开 https://github.com 注册一个账号。
2. 在终端配置你的名字和邮箱（和 GitHub 注册的一致）：
   ```bash
   git config --global user.name "你的名字"
   git config --global user.email "你的邮箱"
   ```

### 3.3 Fork 原题仓库（关键提交动作）
1. 浏览器打开原题地址：https://github.com/Jay-gekko/data-engineer
2. 点击页面右上角 **Fork** 按钮 → 一路确认，会生成 `https://github.com/<你的用户名>/data-engineer`。
3. 把你的 Fork 仓库**设为公开**（Settings → 默认就是 public，确认一下）。

> ⚠️ 题目明确要求：**Fork 到自己的公开仓库**，不要新建空仓库、不要私有仓库。

### 3.4 把 Fork 克隆到本地（等你拿到我给你的代码后做）
```bash
git clone https://github.com/<你的用户名>/data-engineer.git
cd data-engineer
```
之后我会教你怎么把各模块代码 `git add` + `commit`（每个模块单独 commit，message 要有意义）。

---

## 4. 安装 VS Code（看/改代码用，可选但推荐）

```bash
brew install --cask visual-studio-code
```
装完在终端输入 `code .` 即可打开当前文件夹。不懂代码时，用它看文件最直观。

---

## 5. Kaggle 账号（仅 Olist 需要，Q1 免账号）

> **实测结论（重要，别被吓到）**：
> - **Q1 的 Online Retail II**：在 Kaggle 上是**公开数据集**，`download_data.py` 通过 `kagglehub` **匿名即可下载**，**不需要任何 Kaggle 账号**——直接跑就能拿到，根本不用注册。
> - **Q2/Q3 的 Olist**：必须登录 Kaggle 账号才能下载（匿名会 403）。所以你**只需为 Olist 注册一个 Kaggle 账号**，Q1 不用管。

### 5.1 注册 Kaggle（只为 Olist）
1. 打开 https://www.kaggle.com → 右上角 **Register / Sign up**
2. 推荐用 **Google 账号一键注册**，约 1 分钟搞定。
3. 去邮箱点验证链接。

### 5.2 下载 Olist 的两种方式（任选其一）
**方式 A（推荐，零配置）**：登录后打开
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
点页面上的 **Download** 下载 zip，解压后把 9 个 `olist_*.csv` 放进项目的 `data/olist/` 目录即可。
> 这种方式**不需要配 API Token、也不必验证手机号**，最简单。

**方式 B（自动化）**：在 5.3 生成 `kaggle.json` 后，`download_data.py` 会自动下载 Olist。
> ⚠️ 方式 B 首次用 API 时 Kaggle 可能要求**手机号验证**，否则会 403。嫌麻烦就用方式 A。

### 5.3 生成 API Token（仅方式 B 需要）
1. 右上角头像 → **Settings** → 左侧 **API** → 点击 **Create New Token**。
2. 浏览器下载 `kaggle.json`，移动到正确位置并改权限（macOS/Linux 要求 600）：
```bash
mkdir -p ~/.kaggle
mv ~/Downloads/kaggle.json ~/.kaggle/kaggle.json
chmod 600 ~/.kaggle/kaggle.json
```
验证：`ls -l ~/.kaggle/kaggle.json` 应显示 `-rw-------`。

> 小贴士：Q1 的 Online Retail II 不用任何账号，`python download_data.py` 会自动匿名下好；
> 只有 Olist 才会因缺凭证报错——那时你再决定用方式 A 还是 B 补上即可。

---

## 6. MySQL 8.0（Q2 强制，用 Docker 最省事）

题目**强制**用 MySQL 8.0+，不能用 SQLite 替代。最干净的方式是 Docker 起一个容器。

### 6.1 安装 Docker Desktop
打开 https://www.docker.com/products/docker-desktop 下载 macOS 版，按向导安装，启动后菜单栏出现鲸鱼图标即就绪。

### 6.2 一键启动 MySQL 8.0
```bash
docker run -d --name mysql8 \
  -e MYSQL_ROOT_PASSWORD=root \
  -p 3306:3306 \
  mysql:8
```
- `-d`：后台运行
- `-e MYSQL_ROOT_PASSWORD=root`：设 root 密码为 `root`（代码里默认连这个）
- `-p 3306:3306`：把容器 3306 端口映射到本机

**验证容器在跑**：
```bash
docker ps          # 能看到 mysql8 容器且 STATUS 为 Up
```

### 6.3 创建数据库（Q2 灌库用）
本项目 Q2 的 `run_q2.py` 会自动建库并灌入 9 张表。如果你想手动建一个空库：
```bash
docker exec -i mysql8 mysql -uroot -proot -e "CREATE DATABASE IF NOT EXISTS olist;"
```
（输密码时 `-proot` 的密码紧跟 p 后，无空格。）

> 不想用 Docker 的话，也可以用 `brew install mysql` 本机安装，但 Docker 方案对小白最稳，强烈推荐。

---

## 7. LLM API Key（Q4 完整大模型版，推荐）

Q4 用大模型抽取葡萄牙语差评。没有 Key 时代码会**自动降级为规则方法**（仍能跑通、出结果），但有 Key 才能跑「完整大模型版」。

推荐用 OpenAI（便宜、稳）：
1. 打开 https://platform.openai.com 注册并登录。
2. 右上角 → **API keys** → **Create new secret key**，复制保存（只显示一次）。
3. 首次使用需充值少量金额（如 $5），Q4 全部跑完约几美分~1 美元，远低于 $3 预算。

### 7.1 配置 Key（放 .env，绝不提交）
本项目用 `.env` 读密钥。先复制模板：
```bash
cp .env.example .env
```
用 VS Code 或文本编辑打开 `.env`，把你的 key 填进去：
```
OPENAI_API_KEY=sk-xxxx你的key
OPENAI_MODEL=gpt-4o-mini
```

> 🔒 **安全提醒**：`.env` 含密钥，**绝对不要** `git add .env`。项目 `.gitignore` 已忽略它；
> 若你修改 `.gitignore`，只可**追加** `.env` 一行（安全防范），**不可**改动 CSV 相关忽略规则。

---

## 8. 安装 Python 依赖

在 `(.venv)` 激活状态下，进入项目根目录执行：
```bash
# 国内网络更快，建议加清华镜像；官方源慢时可去掉 -i 部分
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```
这会把 pandas、numpy、pyarrow、sqlalchemy、pymysql、kagglehub、openai 等一次性装好。
（本项目已用该镜像装好，正常情况下你无需重装；换机器时照此执行即可。）

**验证**：
```bash
python -c "import pandas, sqlalchemy, kagglehub; print('deps ok')"
```

---

## 9. 一键跑通验证

确保数据、MySQL（Q2 用）、Key（Q4 用）都就绪后：
```bash
python run_all.py
```
或在没配全时，先单独验证不依赖外部服务的模块：
```bash
python run_all.py --only q1 q3      # 只跑 Q1、Q3（只需数据，不需 MySQL/Key）
python check_env.py                 # 看环境体检
```

---

## 常见问题速查

- **`zsh: command not found: brew`** → 第 1 步 Homebrew 没装成功，重跑安装命令。
- **`python` 指向系统旧版本** → 确认执行了 `source .venv/bin/activate`，看到 `(.venv)` 前缀再用。
- **Kaggle 报 403 / 没权限** → `kaggle.json` 权限不对，重跑 `chmod 600 ~/.kaggle/kaggle.json`；也确认账号已登录。
- **MySQL 连不上** → `docker ps` 看容器是否 Up；密码默认 `root`。
- **不想用 Docker** → 可用 `brew install mysql` 本机安装，启动后同样建 `olist` 库。

---
*本手册随项目提供。每完成一项就用 `python check_env.py` 体检，绿灯越多越接近「一键跑通」。*
