# SUBMIT.md —— 提交到 GitHub 的分步手册（macOS 小白版）

> 本项目代码已在本地建好，并做了 **9 个独立 commit（每个模块一个）**。
> 本仓库的本地历史是独立的（根 commit 起）。要交到 GitHub，**必须先 Fork 原仓库**，
> 再把这 9 个 commit「接」到你的 Fork 历史上（用 rebase，不丢历史、不强推）。
>
> 下面的命令请在**你自己的 Mac 终端**里执行（不是这里的对话窗口）。
> 当前项目目录在：`/Users/yangjingwen/WorkBuddy/2026-11-06-22-24-21/data-engineer`

---

## 第 0 步：准备 GitHub 账号
1. 打开 https://github.com ，免费注册并登录。
2. 配置本地 git 身份（已完成 ✅，当前身份）：
   ```bash
   cd /Users/yangjingwen/WorkBuddy/2026-11-06-22-24-21/data-engineer
   git config user.name  "杨婧雯"
   git config user.email "1696098596@qq.com"
   ```
   > 已用真实身份 `杨婧雯 <1696098596@qq.com>` 配置完成。注意：此前 10 个历史提交的 author 仍是占位的 `Candidate`，如需统一可后续 rebase 改写（非必须，不影响提交）。

---

## 第 1 步：Fork 原仓库（关键：必须用 Fork，不要新建空仓库）
1. 浏览器打开 https://github.com/Jay-gekko/data-engineer
2. 点右上角 **Fork** → 确认 **Owner 是你自己**、**Visibility = Public（公开）** → 点 Create fork。
3. Fork 完成后，你会得到一个属于自己的地址：
   ```
   https://github.com/<你的用户名>/data-engineer
   ```
   把 `<你的用户名>` 记下来，下面要用。

---

## 第 2 步：把原仓库设为 upstream，并 rebase（保留我的 9 个 commit）
在终端里执行（把 `<你的用户名>` 换成你自己的）：

```bash
cd /Users/yangjingwen/WorkBuddy/2026-11-06-22-24-21/data-engineer

# 1) 指向原仓库（用于取它的基础历史）
git remote add upstream https://github.com/Jay-gekko/data-engineer.git

# 2) 指向你刚 Fork 出来的仓库
git remote add origin https://github.com/<你的用户名>/data-engineer.git

# 3) 拉取原仓库历史
git fetch upstream

# 4) 把本地 9 个 commit「接」到原仓库历史上（这就是「迭代过程」）
git rebase upstream/main
```

### 如果 rebase 报冲突（大概率只在 README.md / .gitignore）
这是正常的——原仓库也有这两个文件。解决办法：保留**我们这一版**（它已经按考试要求写好），
逐文件执行：
```bash
git checkout --ours README.md
git checkout --ours .gitignore
git add README.md .gitignore
git rebase --continue
```
> 若还有别的冲突，同样 `git checkout --ours <文件> && git add <文件> && git rebase --continue`，
> 直到 rebase 完成。我们的代码不会因为冲突丢失。

---

## 第 3 步：推送到你的 Fork（普通 push，非强推）
```bash
git push -u origin main
```
推送成功后，去 https://github.com/<你的用户名>/data-engineer 确认：
- 仓库是 **Public**
- 能看到 9 个 commit，每个模块一个（看 Commits 页）
- 没有 `data/*.csv`、没有 `.env`（数据集被 .gitignore 忽略，符合要求）

---

## 第 4 步：拿到最终提交 commit hash
```bash
git rev-parse HEAD
```
把输出的一长串哈希（例如 `92c3b68...`）复制下来，和仓库地址一起发邮件。

> ⚠️ 提交截止前**不要再改代码 / 再提交**，否则 hash 会变。
> 题目要 hash 就是为了防止「交完又改」。定稿后只 push 这一次。

---

## 第 5 步：发邮件提交
邮件内容模板：
```
主题：数据工程师笔试 - 提交 - <你的名字>
正文：
1. Git 仓库地址：https://github.com/<你的用户名>/data-engineer
2. 最终 commit hash：<第4步复制的哈希>
3. 运行说明见仓库 README.md / SETUP.md
（可选）环境说明：MySQL 8.0 + Python 3.12，已在本地跑通 Q1/Q3/Q4 规则版
```

---

## 常见问题
**Q：rebase 看不懂，有没有更简单的？**
有「稳妥替代法」：fork 后，`git clone <你的fork>` 到别处，把本目录所有文件复制进 clone，
然后 `git add -A && git commit -m "提交全部解答" && git push`。缺点：commit 变成一个大包，
看不到分模块的迭代过程（扣分点）。**优先用上面的 rebase 法。**

**Q：GitHub 登录要输密码，但提示要用 token？**
GitHub 已不支持密码登录命令行。去 https://github.com/settings/tokens 生成一个
**classic token（勾 repo 权限）**，推送时用户名填你的 GitHub 账号，密码处粘贴 token。

**Q：push 提示鉴权失败？**
确认 origin 地址没错、token 有 repo 权限。或用 GitHub Desktop 图形界面推送更省心。

**Q：本地没装 git？**
```bash
brew install git
```
（brew 的安装见 SETUP.md 第 1 步）
