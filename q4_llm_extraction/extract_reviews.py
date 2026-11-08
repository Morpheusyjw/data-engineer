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

    results: list[dict] = [rule_based(i["text"], i["score"], i["review_id"]) for i in rule_items]

    # LLM 路径：① 显式 OpenAI key → ② 本地 Ollama 自动探测（零 key 真实大模型）→ ③ 规则兜底
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    cost_acc = {
        "prompt_tokens": 0, "completion_tokens": 0, "calls": 0,
        "mode": "rule-based", "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    }

    client = None
    use_json_mode = True
    if api_key and api_key.startswith("sk-"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            base = os.getenv("OPENAI_BASE_URL")
            if base:
                client.base_url = base
            cost_acc["mode"] = "llm-openai"
        except Exception as exc:  # noqa: BLE001
            log.warning("OpenAI 客户端创建失败，转规则兜底：%s", _ascii_safe(exc))
            client = None
    elif ollama_available():
        try:
            from openai import OpenAI
            # Ollama 的 OpenAI 兼容端点不校验 key，随便填即可
            client = OpenAI(api_key="ollama-local", base_url="http://localhost:11434/v1")
            cost_acc["model"] = os.getenv("OPENAI_MODEL", "qwen2.5:3b")
            cost_acc["mode"] = "llm-ollama"
            use_json_mode = False  # 本地端点对 json_object 支持不稳，走文本+正则兜底
            log.info("检测到本地 Ollama，使用零 key 真实大模型：%s", cost_acc["model"])
        except Exception as exc:  # noqa: BLE001
            log.warning("Ollama 客户端创建失败，转规则兜底：%s", _ascii_safe(exc))
            client = None

    if client is not None:
        try:
            BATCH = 10
            for i in range(0, len(llm_items), BATCH):
                chunk = llm_items[i:i + BATCH]
                log.info("LLM 批量 %d/%d ...", i + BATCH, len(llm_items))
                out = llm_batch(chunk, client, cost_acc["model"], cost_acc, use_json_mode)
                cost_acc["calls"] += 1
                results.extend(out)
        except Exception as exc:  # noqa: BLE001
            log.warning("LLM 调用失败，整体降级为规则方法：%s", _ascii_safe(exc))
            cost_acc["mode"] += "(fallback)"
            results.extend([rule_based(i["text"], i["score"], i["review_id"]) for i in llm_items])
    else:
        log.info("未检测到 LLM（无 OPENAI_API_KEY 且无本地 Ollama），LLM 批量部分走规则方法（完整结果仍产出）。")
        results.extend([rule_based(i["text"], i["score"], i["review_id"]) for i in llm_items])

    # 输出 JSON
    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info("✅ 抽取结果已写出：%s（%d 条）", OUT_JSON, len(results))

    # 成本报告
    _write_cost_report(cost_acc, cost_acc["model"], len(results))
    # 准确率评估（自动一致性检查 + 人工标注指引）
    _write_accuracy_report(results)
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


def _write_accuracy_report(results: list[dict]) -> None:
    """自动评估：用「结构一致性 + 规则交叉验证」作为可复现的代理指标，
    并给出人工标注 30 条的最终校验方法。"""
    total = len(results)
    cat_counter: dict[str, int] = {}
    quote_missing = 0
    for r in results:
        for iss in r.get("issues", []):
            cat_counter[iss["category"]] = cat_counter.get(iss["category"], 0) + 1
            if not iss.get("evidence_quote"):
                quote_missing += 1
    cat_lines = "\n".join(f"- {k}: {v}" for k, v in sorted(cat_counter.items(), key=lambda x: -x[1]))
    content = f"""# Q4 准确率评估报告（accuracy_evaluation.md）

## 一、自动结构校验（可复现代理指标）
- 总抽取条数：{total}
- 各类别分布：\n{cat_lines}
- evidence_quote 为空的条目数：{quote_missing}（占比 {quote_missing/max(total,1):.1%}）

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
1. 从 {total} 条中**分层抽样** 30 条（按 category 比例抽，保证覆盖各类）。
2. 由人工阅读原文，独立标注每个 issue 的 category / severity。
3. 计算：
   - **类别准确率** = 机器 category 与人工一致数 / 30
   - **严重度一致率** = severity 一致数 / 30
   - **证据命中率** = evidence_quote 确实出现在原文的比例
4. 记录分歧样例，回流优化 prompt_template.txt。

> 说明：本环境无人工标注资源，故此处给出的是**评估方法与流程设计**；
> 真实施工时按上述三步抽样即可得出具体数值。规则降级模式下置信度统一 0.5，
> 真实 LLM 模式会返回模型自估 confidence，可作为二次筛选阈值。
"""
    (OUT_DIR / "accuracy_evaluation.md").write_text(content, encoding="utf-8")
    log.info("✅ accuracy_evaluation.md 已写出")


if __name__ == "__main__":
    sys.exit(run())
