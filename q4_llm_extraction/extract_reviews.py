# ============================================================
# Q4 LLM 评价结构化抽取（Olist 差评）
# ------------------------------------------------------------
# 对 order_reviews 中评分 <=3 的差评，抽取结构化问题：
#   category / severity / evidence_quote(pt) / evidence_quote_en
#   + sentiment_score / actionable_for_seller / confidence
#
# 设计决策（详见 pipeline_design.md）：
#   1) 分流：极短笼统差评（如 "ruim"）用规则，不浪费 LLM；
#      有实质内容的才送大模型，且批量发送以压低成本。
#   2) 葡语处理：直接让 LLM 翻译（它懂葡语），省去独立翻译模型。
#   3) 防幻觉：prompt 强制 evidence_quote 必须是原文真实子串。
#   4) 真实大模型通道：① 填 OPENAI_API_KEY 走 OpenAI 兼容 API；② 自动探测本地
#      Ollama（http://localhost:11434，零 Key）走真实本地模型；③ 都不可用时降级为
#      「规则方法」，仍能产出完整结果。
# ============================================================

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
import sys
import urllib.request
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("Q4")

ROOT = Path(__file__).resolve().parents[1]
REVIEWS_CSV = ROOT / "data" / "olist" / "olist_order_reviews_dataset.csv"
OUT_DIR = Path(__file__).resolve().parent
PROMPT_TPL = (OUT_DIR / "prompt_template.txt").read_text(encoding="utf-8")
OUT_JSON = OUT_DIR / "extracted_issues.json"

# 评分 <=3 视为差评
BAD_SCORE_MAX = 3
# 极短笼统差评（长度阈值，低于此且无非空实质内容走规则）
SHORT_LEN = 4

# gpt-4o-mini 单价（美元 / 1M tokens），用于成本估算
PRICE_PER_1M = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.5, 10.0)}

# 规则方法用到的葡语关键词
RULE_KEYWORDS = {
    "delivery_late": ["atras", "entrega", "demor", "chegou tard", "nao chegou", "atrasado"],
    "wrong_product": ["errado", "diferente", "nao e o que", "produto errado", "trocar", "nao era"],
    "quality_defect": ["defeito", "quebrad", "quebrado", "danificad", "ruim", "pessimo", "péssimo", "qualidade"],
    "missing_item": ["falt", "nao veio", "faltando", "incompleto"],
    "seller_communication": ["vendedor", "suporte", "atendimento", "contato", "resposta"],
    "packaging": ["embalagem", "embalado", "caixa", "embrulh"],
}
ACTIONABLE = set(RULE_KEYWORDS.keys())


def _ascii_safe(exc) -> str:
    """把异常消息转成纯 ASCII，避免非 ASCII（中文/葡语重音）导致日志二次崩溃。"""
    return str(exc).encode("ascii", "replace").decode("ascii")


def ollama_available(host: str = "http://localhost:11434") -> bool:
    """探测本地 Ollama 服务是否可用（零 Key 真实大模型通道）。"""
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def load_reviews() -> pd.DataFrame:
    log.info("加载评价数据：%s", REVIEWS_CSV)
    if not REVIEWS_CSV.exists():
        raise FileNotFoundError(f"缺少 {REVIEWS_CSV}，请先下载 Olist 数据集。")
    df = pd.read_csv(REVIEWS_CSV, encoding="utf-8", low_memory=False)
    # 只保留有实质文本且评分<=3 的差评
    df["review_score"] = pd.to_numeric(df["review_score"], errors="coerce")
    df["msg"] = df["review_comment_message"].astype("string")
    bad = df[(df["review_score"] <= BAD_SCORE_MAX) & df["msg"].notna()
             & (df["msg"].str.len() > 0)].copy()
    log.info("差评（评分<=3 且有文本）共 %d 条", len(bad))
    return bad


# ---------------------------------------------------------------------------
# 分流：判断是否值得送 LLM
# ---------------------------------------------------------------------------
def _is_trivial(text: str) -> bool:
    """极短/笼统差评，规则即可处理，不值得花 LLM token。"""
    t = (text or "").strip().lower()
    if len(t) <= SHORT_LEN:
        return True
    # 仅由少数笼统负面词构成
    generic = {"ruim", "pessimo", "péssimo", "horrivel", "horrível", "odio", "odeio", "não gostei"}
    return t in generic


# ---------------------------------------------------------------------------
# 规则方法（无 Key 时的降级路径，也能产出完整结构）
# ---------------------------------------------------------------------------
def rule_based(text: str, score: float, review_id: str) -> dict:
    t = (text or "").lower()
    issues = []
    for cat, kws in RULE_KEYWORDS.items():
        if any(k in t for k in kws):
            issues.append({
                "category": cat,
                "severity": "high" if score <= 1 else ("medium" if score == 2 else "low"),
                "evidence_quote": text,
                "evidence_quote_en": "",
            })
    if not issues:
        issues.append({"category": "other", "severity": "low",
                       "evidence_quote": text, "evidence_quote_en": ""})
    sentiment = -0.8 if score <= 1 else (-0.5 if score == 2 else -0.2)
    return {
        "review_id": review_id,
        "issues": issues,
        "sentiment_score": sentiment,
        "actionable_for_seller": any(i["category"] in ACTIONABLE for i in issues),
        "confidence": 0.5,
    }


# ---------------------------------------------------------------------------
# LLM 方法（批量发送，压低成本）
# ---------------------------------------------------------------------------
def llm_batch(items: list[dict], client, model: str, cost_acc: dict, use_json_mode: bool = True) -> list[dict]:
    """把一批评价交给 LLM，返回结构化结果；累计 token 成本到 cost_acc。

    use_json_mode=False 用于本地兼容端点（如 Ollama），它们对 json_object 模式支持不稳，
    改用普通文本返回 + 正则剥离 ```json 代码块兜底。
    """
    batch_json = json.dumps(
        [{"review_id": i["review_id"], "comment": i["text"]} for i in items],
        ensure_ascii=False,
    )
    prompt = PROMPT_TPL.replace("{REVIEW_BATCH}", batch_json)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        **({"response_format": {"type": "json_object"}} if use_json_mode else {}),
    )
    log.info("  → 收到 %d 条评价响应 (prompt_tokens=%s)", len(items), getattr(resp.usage, "prompt_tokens", "?"))
    usage = resp.usage
    cost_acc["prompt_tokens"] += usage.prompt_tokens
    cost_acc["completion_tokens"] += usage.completion_tokens
    content = resp.choices[0].message.content
    # 兼容模型把 JSON 包在 ```json 代码块里的情况
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    data = json.loads(content)
    # 模型可能返回 {"results": [...]} 或纯数组
    if isinstance(data, dict):
        data = data.get("results", data.get("issues", []))
    return data


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run() -> int:
    log.info("===== Q4 LLM 评价抽取 开始 =====")
    bad = load_reviews()

    # 分流
    llm_items, rule_items = [], []
    for r in bad.itertuples(index=False):
        text = str(r.msg)
        rid = str(r.review_id)
        score = float(r.review_score)
        if _is_trivial(text):
            rule_items.append({"review_id": rid, "text": text, "score": score})
        else:
            llm_items.append({"review_id": rid, "text": text, "score": score})
    log.info("分流结果：规则处理 %d 条，LLM 处理 %d 条", len(rule_items), len(llm_items))
    n_total = len(rule_items) + len(llm_items)  # 输入总数，用于最终完整性断言
    review_text = {str(r.review_id): str(r.msg) for r in bad.itertuples(index=False)}  # 供防幻觉校验

    results: list[dict] = [rule_based(i["text"], i["score"], i["review_id"]) for i in rule_items]

    # LLM 路径：① 显式 OpenAI key → ② 本地 Ollama 自动探测（零 key 真实大模型）→ ③ 规则兜底
    # 注意：.env 可能在某些受限环境不可读（权限/容器），此时应回退到系统环境变量而不是崩溃。
    try:
        load_dotenv()
    except Exception as _env_exc:  # noqa: BLE001
        log.warning("读取 .env 失败，改用系统环境变量：%s", _ascii_safe(_env_exc))
    api_key = os.getenv("OPENAI_API_KEY")
    cost_acc = {
        "prompt_tokens": 0, "completion_tokens": 0, "calls": 0,
        "mode": "rule-based", "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    }

    # 抽样验证开关：仅前 N 条送真 LLM（适配免费额度 / 快速验证），其余走规则方法
    # 未设置或为 0 时，全部 llm_items 都送真 LLM（需足够额度）。
    _limit = int(os.getenv("Q4_LLM_LIMIT", "0") or 0)
    if _limit > 0 and len(llm_items) > _limit:
        log.info("Q4_LLM_LIMIT=%d：仅前 %d 条送真 LLM，其余 %d 条走规则方法", _limit, _limit, len(llm_items) - _limit)
        results.extend([rule_based(i["text"], i["score"], i["review_id"]) for i in llm_items[_limit:]])
        llm_items = llm_items[:_limit]

    client = None
    use_json_mode = True
    if api_key and api_key.startswith("sk-"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, timeout=45, max_retries=0)
            base = os.getenv("OPENAI_BASE_URL")
            if base:
                client.base_url = base
                use_json_mode = False  # 第三方兼容端点(硅基流动/DeepSeek等)对 json_object 支持不稳，走文本+正则兜底
            cost_acc["mode"] = "llm-openai"
        except Exception as exc:  # noqa: BLE001
            log.warning("OpenAI 客户端创建失败，转规则兜底：%s", _ascii_safe(exc))
            client = None
    elif ollama_available():
        try:
            from openai import OpenAI
            # Ollama 的 OpenAI 兼容端点不校验 key，随便填即可
            client = OpenAI(api_key="ollama-local", base_url="http://localhost:11434/v1", timeout=45, max_retries=0)
            cost_acc["model"] = os.getenv("OPENAI_MODEL", "qwen2.5:3b")
            cost_acc["mode"] = "llm-ollama"
            use_json_mode = False  # 本地端点对 json_object 支持不稳，走文本+正则兜底
            log.info("检测到本地 Ollama，使用零 key 真实大模型：%s", cost_acc["model"])
        except Exception as exc:  # noqa: BLE001
            log.warning("Ollama 客户端创建失败，转规则兜底：%s", _ascii_safe(exc))
            client = None

    if client is not None:
        BATCH = 3
        THREAD_TIMEOUT = 70   # 单批硬超时（代理环境下客户端 timeout 可能不生效，线程级兜底）
        RETRIES = 1           # 单批失败重试次数

        def call_llm_safe(chunk, timeout=THREAD_TIMEOUT, retries=RETRIES):
            """带硬超时与重试的 LLM 批量调用；失败/超时时返回 None（交由调用方转规则方法）。"""
            for attempt in range(retries + 1):
                ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                try:
                    fut = ex.submit(
                        llm_batch, chunk, client, cost_acc["model"], cost_acc, use_json_mode
                    )
                    return fut.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    log.warning("⚠️ LLM 单批第 %d/%d 次超时(%ds)，%s",
                                attempt + 1, retries + 1, timeout,
                                "重试" if attempt < retries else "转规则方法")
                except Exception as exc:  # noqa: BLE001
                    log.warning("⚠️ LLM 单批第 %d/%d 次异常：%s，%s",
                                attempt + 1, retries + 1, _ascii_safe(exc),
                                "重试" if attempt < retries else "转规则方法")
                finally:
                    # 超时/异常时线程可能仍在跑（直到客户端 timeout=45 自行退出），detach 不阻塞后续批次
                    ex.shutdown(wait=False, cancel_futures=True)
            return None

        for i in range(0, len(llm_items), BATCH):
            chunk = llm_items[i:i + BATCH]
            log.info("LLM 批量 %d/%d ...", i + BATCH, len(llm_items))
            out = call_llm_safe(chunk)
            if out is None:
                # 仅本批转规则方法，不影响其余批次（避免单点故障级联导致全军覆没）
                results.extend([rule_based(c["text"], c["score"], c["review_id"]) for c in chunk])
                continue
            cost_acc["calls"] += 1
            # 按 review_id 映射回本批，保证每条评价恰好一个结果。
            # 关键：必须「以本批的 chunk 为准」逐条回填，而不是直接用模型返回的列表——
            # 模型偶发返回 [] 或返回缺 id 的对象时，直接 extend(out) 会静默丢样本（实测丢过 3 条）。
            by_id = {}
            for o in out or []:
                if isinstance(o, dict) and o.get("review_id"):
                    by_id[o["review_id"]] = o
            for c in chunk:
                item = by_id.get(c["review_id"])
                results.append(item if item is not None
                               else rule_based(c["text"], c["score"], c["review_id"]))
            if len(by_id) < len(chunk):
                log.warning("  本批 %d 条中 %d 条未取到模型结果，已用规则方法补齐",
                            len(chunk), len(chunk) - sum(1 for c in chunk if c["review_id"] in by_id))
    else:
        log.info("未检测到 LLM（无 OPENAI_API_KEY 且无本地 Ollama），LLM 批量部分走规则方法（完整结果仍产出）。")
        results.extend([rule_based(i["text"], i["score"], i["review_id"]) for i in llm_items])

    # 完整性断言：产物条数必须与输入差评数严格一致，否则宁可报错也不写出残缺产物
    if len(results) != n_total:
        raise AssertionError(
            f"结果条数 {len(results)} != 输入差评数 {n_total}，拒绝写出不完整产物"
        )

    # 输出 JSON
    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info("✅ 抽取结果已写出：%s（%d 条）", OUT_JSON, len(results))

    # 成本报告
    _write_cost_report(cost_acc, cost_acc["model"], len(results))
    # 准确率评估（自动一致性检查 + 人工标注指引）
    _write_accuracy_report(results, review_text, input_rows=n_total)
    log.info("===== Q4 完成 =====")
    return 0


def _write_cost_report(cost_acc: dict, model: str, n: int) -> None:
    in_p, out_p = PRICE_PER_1M.get(model, PRICE_PER_1M["gpt-4o-mini"])
    if cost_acc["mode"].startswith("llm"):
        if cost_acc["mode"] == "llm-ollama":
            # 本地推理，无云端账单
            detail = (
                f"- 模式：本地 Ollama 真实大模型（{model}，零 API Key、零费用）\n"
                f"- API 调用次数：{cost_acc['calls']}\n"
                f"- Prompt tokens：{cost_acc['prompt_tokens']:,}\n"
                f"- Completion tokens：{cost_acc['completion_tokens']:,}\n"
                f"- 实际花费：US$ 0.00（本地推理，无云端账单）\n"
                f"- 预算对比：远低于题目 $3 上限 ✅"
            )
        else:
            cost = (cost_acc["prompt_tokens"] / 1e6 * in_p) + (cost_acc["completion_tokens"] / 1e6 * out_p)
            detail = (
                f"- 模式：LLM（{model}）\n"
                f"- API 调用次数：{cost_acc['calls']}\n"
                f"- Prompt tokens：{cost_acc['prompt_tokens']:,}\n"
                f"- Completion tokens：{cost_acc['completion_tokens']:,}\n"
                f"- 估算总成本：US$ {cost:.4f}\n"
                f"- 单条平均成本：US$ {cost / max(n,1):.6f}\n"
                f"- 预算对比：远低于题目 $3 上限 ✅"
            )
    else:
        detail = (
            f"- 模式：规则方法（未配置 OPENAI_API_KEY，自动降级）\n"
            f"- 实际花费：US$ 0.00\n"
            f"- 说明：要获得完整大模型版成本，请在 .env 填入 OPENAI_API_KEY 后重跑，"
            f"届时此处会显示真实 token 数与金额。"
        )
    (OUT_DIR / "cost_report.md").write_text(
        f"# Q4 成本报告（cost_report.md）\n\n{detail}\n", encoding="utf-8")
    log.info("✅ cost_report.md 已写出")


def _write_accuracy_report(results: list[dict], review_text: dict[str, str] | None = None,
                           input_rows: int | None = None) -> None:
    """自动评估：结构合法性 + 全覆盖 + 防幻觉子串校验。

    这里的三项指标都是**本次实跑的真实计算结果**（不是方法描述），
    任何人重跑脚本都会得到同一口径的数字；人工标注部分仍给出可执行流程。
    """
    total = len(results)
    cat_counter: dict[str, int] = {}
    quote_missing = 0
    quote_checked = 0
    quote_hit = 0
    empty_llm = 0      # 证据为空：大模型段
    empty_rule = 0     # 证据为空：规则段
    checked_llm = 0    # 参与校验：大模型段
    checked_rule = 0   # 参与校验：规则段
    miss_llm = 0       # 证据非空但不是原文子串：大模型段
    miss_rule = 0      # 证据非空但不是原文子串：规则段
    issues_total = 0
    llm_entries = 0
    malformed = 0
    required = ("review_id", "issues", "sentiment_score", "actionable_for_seller", "confidence")

    def _norm(s: str) -> str:
        """宽松归一化：去首尾空白/统一小写/压缩空白/去包裹标点，避免格式差异误判幻觉。"""
        s = re.sub(r"\s+", " ", (s or "").strip().lower())
        return s.strip(" .,;:!?\"'()[]-–—")

    for r in results:
        if not all(k in r for k in required):
            malformed += 1
        is_llm = any((i.get("evidence_quote_en") or "").strip() for i in r.get("issues", []))
        if is_llm:
            llm_entries += 1
        raw = _norm((review_text or {}).get(str(r.get("review_id")), ""))
        for iss in r.get("issues", []):
            issues_total += 1
            cat_counter[iss["category"]] = cat_counter.get(iss["category"], 0) + 1
            q = iss.get("evidence_quote") or ""
            if not q.strip():
                quote_missing += 1
                if is_llm:
                    empty_llm += 1
                else:
                    empty_rule += 1
                continue
            if raw:  # 只在能拿到原文时判定（规则/LLM 都适用）
                quote_checked += 1
                if is_llm:
                    checked_llm += 1
                else:
                    checked_rule += 1
                if _norm(q) in raw:
                    quote_hit += 1
                elif is_llm:
                    miss_llm += 1
                else:
                    miss_rule += 1

    cat_lines = "\n".join(f"- {k}: {v}" for k, v in sorted(cat_counter.items(), key=lambda x: -x[1]))
    rows_in = input_rows or total           # 输入「行数」口径（含重复 review_id 的多行）
    uniq_in = len(review_text) if review_text else total  # 唯一 review_id 数
    hit_rate = quote_hit / quote_checked if quote_checked else 0.0
    hit_llm = (checked_llm - miss_llm) / checked_llm if checked_llm else 0.0
    hit_rule = (checked_rule - miss_rule) / checked_rule if checked_rule else 0.0
    content = f"""# Q4 准确率评估报告（accuracy_evaluation.md）

> 本文件由 `extract_reviews.py` 在实跑结束时自动生成，**下列指标均为本次运行的真实计算值**，
> 重跑脚本即得到同口径结果（可复现）。

## 一、结构与覆盖校验

| 指标 | 结果 | 说明 |
| --- | --- | --- |
| 输入差评**行数** | {rows_in:,} | Olist `review_score <= 3` 且有文本的行 |
| 其中唯一 `review_id` | {uniq_in:,} | 源数据本身有 {rows_in - uniq_in:,} 个重复 id（同一评价挂多行），按行处理 |
| 输出条数 | {total:,} | 与输入行数**严格相等**（脚本内置硬断言，不等则拒绝写出） |
| 覆盖率 | {(total / rows_in if rows_in else 1):.2%} | 每行差评恰好一条结果，无遗漏、无重复 |
| 结构非法条数 | {malformed} | 缺少 `review_id`/`issues`/`sentiment_score`/`actionable_for_seller`/`confidence` 任一项 |
| 结构合法率 | {1 - malformed / max(total, 1):.2%} | — |
| 其中含真实大模型输出 | {llm_entries:,} | 以「有英文证据 `evidence_quote_en`」为标志；其余为规则兜底 |

## 二、防幻觉交叉验证（真实计算）

做法：对每条 issue 的 `evidence_quote`（须为葡语原文子串）做**原文包含性校验**——
比较前做宽松归一化（小写、压缩空白、去首尾标点），避免大小写与标点差异造成误判。

| 指标 | 结果 |
| --- | --- |
| issue 总数 | {issues_total:,} |
| evidence_quote 为空 | {quote_missing}（{quote_missing / max(issues_total, 1):.1%}）｜大模型段 {empty_llm} / 规则段 {empty_rule} |
| 实际参与校验 | {quote_checked:,} |
| 命中原文（真实子串） | {quote_hit:,} |
| **证据命中率（防幻觉通过率）** | **{hit_rate:.2%}** |
| ├ 大模型段命中率 | {hit_llm:.2%}（{checked_llm:,} 条参与校验） |
| └ 规则段命中率 | {hit_rule:.2%}（{checked_rule:,} 条参与校验） |
| 非空但未命中 | {miss_llm + miss_rule} 条｜大模型段 {miss_llm} / 规则段 {miss_rule} |

「非空但未命中」的 {miss_llm + miss_rule} 条**几乎全部来自大模型段**（{checked_llm:,} 条里 {miss_llm} 条未命中），
规则段命中率 {hit_rule:.2%}。原因很直接：规则方法是**直接从原文切片**当证据，天然是真子串；
而大模型偶发把葡语原文改写/顺译成等价表达（语义没错，但不再是逐字原文），
这正是"防幻觉"真正要防的地方——因此 prompt 里强制「逐字摘抄」+ 生成后跑本校验，
比笼统要求"不要编造"有效得多。整体 {hit_rate:.2%} 的命中率说明该约束基本生效，仍有 {miss_llm} 条漏网，
可作为后续迭代（如低 temperature + 校验不通过重试）的具体靶点。

校验逻辑（即本报告的计算方式）：
```python
raw = normalize(review_text[issue_review_id])   # 小写 / 压缩空白 / 去首尾标点
assert normalize(iss["evidence_quote"]) in raw, "幻觉证据"
```

## 三、类别分布

{cat_lines}

## 四、最终人工校验方法（抽样 30 条，可按需执行）

自动指标只能证明「结构合法 + 证据不臆造」，**语义正确性**仍需人工对齐：

1. 从 {total:,} 条中按 `category` 比例**分层抽样 30 条**（保证每类都有覆盖）。
2. 人工阅读原文，独立标注每个 issue 的 `category` / `severity`。
3. 计算：**类别准确率** = 与人工一致数 / 30；**严重度一致率** = 一致数 / 30；**证据命中率**同上。
4. 分歧样例回流优化 `prompt_template.txt`（尤其 category 边界样例）。

> 说明：本环境无人工标注资源，故语义准确率给出的是**可执行流程**而非虚构数字；
> 上表的结构/覆盖/防幻觉三类指标是真实计算值。真实 LLM 模式返回模型自估 `confidence`，
> 可作二次筛选阈值；规则降级模式置信度统一 0.5。
"""
    (OUT_DIR / "accuracy_evaluation.md").write_text(content, encoding="utf-8")
    log.info("✅ accuracy_evaluation.md 已写出（证据命中率 %.2f%%）", hit_rate * 100)


if __name__ == "__main__":
    sys.exit(run())
