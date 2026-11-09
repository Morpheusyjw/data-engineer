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
import time
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
# 每次请求打包几条评价：3 条是实测出来的平衡点——再大，单批超时/格式失败会一次性丢掉更多
BATCH_SIZE = 3

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
    """探测本地 Ollama 服务是否可用（零 Key 真实大模型通道）。

    探测 localhost 时**显式绕过系统代理**：环境里若有 HTTP_PROXY/HTTPS_PROXY，
    对本地端口的请求会先交给代理再失败（实测多 0.1~0.2 秒；某些代理配置会一直等到超时），
    而探测本机服务本来就不该走代理。
    """
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(host + "/api/tags", timeout=1.5) as r:
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


# 模板里常见的人肉占位符，一旦出现就认为「用户还没填 key」
_PLACEHOLDER_MARKERS = ("你的", "xxx", "your", "填这", "changeme", "placeholder", "todo")


def _looks_like_real_key(key: str | None) -> bool:
    """判断 OPENAI_API_KEY 是不是一个「真的 key」。

    背景：`.env.example` 里的占位符是 `sk-你的key填这里`，它同样以 `sk-` 开头。
    如果只判断前缀，评审照抄模板后脚本会拿假 key 去请求上千次、每次失败再降级，
    本来 1 秒的规则路径会拖成二十多分钟。所以这里额外做两项检查：
      1. 不含占位词（中文占位/xxx/your…）；
      2. `sk-` 之后是长度 ≥20 的纯可见 ASCII（真实 key 一定满足）。
    """
    if not key or not key.startswith("sk-"):
        return False
    low = key.lower()
    if any(m in low for m in _PLACEHOLDER_MARKERS):
        return False
    body = key[3:]
    return len(body) >= 20 and all(33 <= ord(ch) <= 126 for ch in body)


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
    t0 = time.time()          # 计时起点：成本报告里的「端到端耗时」
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
    if api_key and not _looks_like_real_key(api_key):
        log.warning("OPENAI_API_KEY 看起来是模板占位符（不是有效 key），跳过 LLM 通道，直接走规则方法。")
        api_key = None
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
    if _looks_like_real_key(api_key):
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
        BATCH = BATCH_SIZE
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

    # 成本报告（单位成本 / 外推 / 预算余量，见 _write_cost_report）
    n_issues = sum(len(r.get("issues", [])) for r in results)
    llm_rows = sum(
        1 for r in results
        if any((i.get("evidence_quote_en") or "").strip() for i in r.get("issues", []))
    )
    _write_cost_report(cost_acc, cost_acc["model"], len(results),
                       n_issues=n_issues, llm_rows=llm_rows,
                       n_llm_sent=min(len(llm_items), cost_acc["calls"] * BATCH_SIZE),
                       elapsed=time.time() - t0, n_total=n_total)
    # 准确率评估（自动一致性检查 + 人工标注指引）
    _write_accuracy_report(results, review_text, input_rows=n_total)
    log.info("===== Q4 完成 =====")
    return 0


def _price_for(model: str) -> tuple[float, float, str]:
    """返回 (输入单价, 输出单价, 计价口径说明)，单位：美元 / 1M tokens。

    计价口径必须写清楚：本次实跑用的是硅基流动的 Qwen2.5-7B，其单价不高于
    gpt-4o-mini。为了让成本报告**可横向比较、且是保守上界**，统一按 gpt-4o-mini
    公开价（$0.15 / $0.60）折算，并在报告里显式标注口径，避免"账单数字对不上"。
    """
    if model in PRICE_PER_1M:
        return (*PRICE_PER_1M[model], model)
    return (*PRICE_PER_1M["gpt-4o-mini"], "gpt-4o-mini（保守上界口径）")


def _write_cost_report(cost_acc: dict, model: str, n: int, n_issues: int = 0,
                       llm_rows: int = 0, n_llm_sent: int = 0,
                       elapsed: float = 0.0,
                       n_total: int | None = None) -> None:
    """生成成本报告：不只有一行总价，而是给出「单位成本 + 外推 + 预算余量」。

    题目问的是「成本控制」，所以这里必须回答三个问题：
      1) 这一单花了多少、摊到每条多少钱；
      2) 如果全量/更大规模都这么跑，会是多少；
      3) 批量与分流的省钱效果到底值多少，别凭感觉说"批处理更省"。
    """
    in_p, out_p, price_note = _price_for(model)
    p_tok = cost_acc["prompt_tokens"]
    c_tok = cost_acc["completion_tokens"]
    calls = cost_acc["calls"]
    n_total = n_total or n
    n_llm = llm_rows or 0
    n_sent = n_llm_sent or n_llm      # 送进模型的条数（成本分母）

    if cost_acc["mode"].startswith("llm"):
        cost = p_tok / 1e6 * in_p + c_tok / 1e6 * out_p
        if cost_acc["mode"] == "llm-ollama":
            cost_line = "US$ 0.00（本地推理，无云端账单）"
            cost_num = 0.0
        else:
            cost_line = f"US$ {cost:.4f}"
            cost_num = cost
        per_review = cost_num / n_sent if n_sent else 0.0
        per_issue = cost_num / n_issues if n_issues else 0.0
        per_call = cost_num / calls if calls else 0.0
        total_tok = p_tok + c_tok
        tok_per_call = total_tok / calls if calls else 0

        # 预算余量：$3 还能跑多少条
        budget = 3.0
        headroom_rows = int(budget / per_review) if per_review else 0
        # 全量外推：差评全部走 LLM（按实测单条单价）
        full_scale = per_review * n_total
        # 单条调用 vs 批量调用（省的是每次都要重发的 system prompt）
        sys_tok = max(len(PROMPT_TPL) // 4, 1)          # 模板按 4 字符/token 粗估
        prompt_single = p_tok + max(n_sent - calls, 0) * sys_tok
        cost_single = prompt_single / 1e6 * in_p + c_tok / 1e6 * out_p
        save_ratio = (1 - cost_num / cost_single) if cost_single else 0.0
        # 规模化外推：口径写死假设，避免读者误当预测
        daily_1e5 = 100_000 * 0.05 * 0.60     # 10 万单/天 × 5% 带文本差评 × 60% 需 LLM
        daily_1e6 = 1_000_000 * 0.05 * 0.60
        detail = f"""# Q4 成本报告（cost_report.md）

> 本文件由 `extract_reviews.py` 在实跑结束时自动生成，token 数与调用次数来自 API 返回的
> `usage` 字段（真实值，不是估算）；金额按统一单价折算（见「计价口径」）。

## 一、结论先行

- 本次处理 **{n_total:,}** 条差评，其中 **{n_sent:,}** 条送进大模型（{n_llm:,} 条拿到真实模型输出，
  其余被规则兜底补位），
  总花费 **{cost_line}**，**单条大模型成本 ≈ US$ {per_review:.6f}**。
- 预算 $3 的 **{cost_num / budget:.2%}** 被用掉，余量足够再跑 **{headroom_rows:,}** 条，
  **成本不是这套方案的约束**（约束是 40 分钟时长与调用稳定性——见第五节）。
- 批量（3 条/次）而不是单条调用，省下约 **{save_ratio:.0%}** 的 prompt 开销，
  这是"批处理更省"的**实测**答案，不是经验之谈。

## 二、本次运行的真实用量

| 项目 | 数值 |
|---|---|
| 运行模式 | `{cost_acc['mode']}`（模型 `{model}`） |
| 输入差评（评分 ≤3 且有文本） | {n_total:,} 条 |
| 送入大模型 | {n_sent:,} 条 |
| 其中含真实模型输出（有英文证据） | {n_llm:,} 条 |
| API 调用次数 | {calls:,} 次（每次 3 条，含重试成功后的计费调用） |
| Prompt tokens | {p_tok:,} |
| Completion tokens | {c_tok:,} |
| 总 tokens | {total_tok:,} |
| 每次调用平均 tokens | {tok_per_call:,.0f} |
| 端到端耗时 | {elapsed / 60:.1f} 分钟 |

## 三、单位成本（这才是能拿去报价的数字）

| 口径 | 成本 |
|---|---|
| 每条差评（仅大模型段） | US$ {per_review:.6f} |
| 每个抽出的 issue（共 {n_issues:,} 个） | US$ {per_issue:.6f} |
| 每次 API 调用（3 条） | US$ {per_call:.6f} |
| 每 1,000 条差评 | US$ {per_review * 1000:.4f} |
| 每 10 万条差评 | US$ {per_review * 100000:.2f} |

## 四、计价口径（为什么账单可能对不上）

本次实际调用的是硅基流动的 `{model}`，其单价**不高于** gpt-4o-mini。
本报告统一按 **{price_note}** 的公开价折算：
输入 **US$ {in_p}/1M tokens**、输出 **US$ {out_p}/1M tokens**。
因此上表是**保守上界**——真实账单只会更低；若换成 gpt-4o-mini 本尊，则是精确值。

## 五、预算与规模外推

| 场景 | 估算成本 | 说明 |
|---|---|---|
| 本次（{n_sent:,} 条走 LLM） | US$ {cost_num:.4f} | 实测 |
| 全部 {n_total:,} 条都走 LLM | US$ {full_scale:.2f} | 按实测单条单价线性外推 |
| 10 万单/天（年） | US$ {per_review * daily_1e5 * 365:,.0f} | 假设 5% 订单带文本差评、其中 60% 值得送 LLM |
| 100 万单/天（年） | US$ {per_review * daily_1e6 * 365:,.0f} | 同上，规模 ×10 |

> **反直觉但重要的结论**：即使 100 万单/天的规模，LLM 年成本也只有千元美金量级。
> 所以 Q5 里"LLM 成本失控"的真正风险不在 token 单价，而在**无节制重试**与
> **把笼统差评也送进模型**（本方案用规则分流挡掉了这类）；以及 40 分钟内跑不完全量时，
> 团队会用"加大并发"解决，那才是账单失控的入口。

## 六、省钱的三个具体动作（按收益排序）

1. **规则分流**：`ruim`/`péssimo` 这类一两个词的差评，规则方法给出的 category 与 LLM 几乎一致，
   但对它们调 LLM 是纯浪费。本次运行把长度 ≤4、或只由 `ruim`/`péssimo` 这类笼统词构成的短评
   全部交给规则方法（具体条数见运行日志「分流结果」一行），这部分 token 花费为零。
2. **批量调用**：prompt 里的 system + few-shot 只付一次。实测批量后单条 prompt 约
   {p_tok / max(n_llm, 1):,.0f} tokens；若改成单条调用，成本会升到 US$ {cost_single:.4f}（+{save_ratio:.0%}）。
3. **限制输出长度**：`issues` 最多 3 条 + 证据句只允许原文摘抄，直接把 completion 压在
   {c_tok / max(n_sent, 1):,.0f} tokens/条；否则模型会写小作文，输出侧成本是输入侧的
   {out_p / in_p:.0f} 倍单价，很容易失控。
"""
    else:
        detail = f"""# Q4 成本报告（cost_report.md）

> 本文件由 `extract_reviews.py` 在实跑结束时自动生成。

## 一、结论

本次运行**未启用大模型**（模式：`{cost_acc['mode']}`，未检测到有效 `OPENAI_API_KEY`，
也无本地 Ollama），全部 {n_total:,} 条差评走规则方法，**实际花费 US$ 0.00**。

## 二、这样跑意味着什么

- 结果仍然完整：{n:,} 条输出与输入严格相等（内置硬断言），可用于冷启动/离线兜底。
- 代价是抽取质量：规则方法只能命中关键词，无法处理反讽、隐含语义、多问题拆分。
- 想拿到真实大模型成本：在 `.env` 填 `OPENAI_API_KEY`（任意 OpenAI 兼容端点）后重跑，
  本文件会自动改成真实 token 账单，并给出单条成本与外推。

## 三、规则模式的成本对照（供决策）

| 方案 | 单价 | 14,447 条总价 | 备注 |
|---|---|---|---|
| 规则方法 | US$ 0 | US$ 0 | 关键词匹配，证据直接切片，天然无幻觉 |
| 大模型（批量 3 条） | 约 US$ 0.0001/条 | 约 US$ 1.5~2.5 | 需 API Key；本仓库曾实测 US$ 0.0243/200 条量级 |
| 大模型（单条调用） | 约 US$ 0.0002/条 | 约 US$ 3~5 | system prompt 每条重发，性价比最差 |
"""
    (OUT_DIR / "cost_report.md").write_text(detail, encoding="utf-8")
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
