#!/usr/bin/env python3
"""RAGNEXUS 评测体系 v2：检索层 + 生成层双评测

对比三路检索策略（单路向量 / 混合+RRF / 混合+Reranker），
并对完整问答链路做 LLM-as-judge 打分（忠实度 + 相关性）。

用法:
  python eval_rag.py                           # development 24 题（检索层 + 生成层）
  python eval_rag.py --retrieval-only          # 只跑检索层（快，不调生成）
  python eval_rag.py --split heldout --allow-heldout  # 解锁 heldout 16 题
  python eval_rag.py --generation-only         # 只跑生成层
  python eval_rag.py --set eval/eval_set.json  # 指定评测集
  python eval_rag.py --out eval/results.json   # 指定结果输出

依赖: 仅标准库。服务需在线（localhost:8000），.env 提供 API key。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

from eval_dataset import load_and_validate_eval_set, select_questions

# ---------------------------------------------------------------- 配置

API = os.getenv("RAGNEXUS_API", "http://localhost:8000")
API_KEY = os.getenv("RAG_API_KEY", "rag-secret-key-2024")
LLM_BASE = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")

HDR = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# 检索策略 -> (/query/hybrid 参数, 结果字段)
# 口径说明：1.0/2.0 暂作为生产 baseline；旧关键词评测已失效，
# Hybrid/Reranker 是否有增益必须等 V2 ground truth 与 held-out 报告复验。
STRATEGIES = [
    ("dense",    {"strategy": "dense", "use_reranker": False}, "dense_top"),
    ("hybrid",   {"strategy": "hybrid", "use_reranker": False}, "hybrid_top"),
    ("reranked", {"strategy": "reranked", "use_reranker": True}, "reranked"),
]


def load_env(path=".env"):
    """加载 .env（不覆盖已存在的环境变量）"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v


load_env()
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
API_KEY = os.getenv("RAG_API_KEY", API_KEY)


# ---------------------------------------------------------------- HTTP

def api_post(path, body, timeout=90, retries=6):
    """POST JSON。429 限流时指数退避重试（后端默认限流 30 次/分钟，评测多策略并发必触发）。"""
    for attempt in range(retries):
        req = urllib.request.Request(
            f"{API}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=HDR,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 2 * (attempt + 1)  # 2s, 4s, 6s, 8s, 10s
                print(f" [429 限流，{wait}s 后重试]", end="", flush=True)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("api_post 重试耗尽")



def llm_chat(messages, temperature=0):
    """调 DeepSeek（OpenAI 兼容协议）"""
    if not DEEPSEEK_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，无法做生成层评测（可加 --retrieval-only）")
    req = urllib.request.Request(
        f"{LLM_BASE}/v1/chat/completions",
        data=json.dumps({
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }).encode("utf-8"),
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------- 指标

def _relevant_id_set(relevant_ids):
    if not relevant_ids:
        raise ValueError("relevant_ids 必须包含至少一个 chunk ID")
    normalized = set()
    for index, relevant_id in enumerate(relevant_ids):
        if not isinstance(relevant_id, str) or not relevant_id.strip():
            raise ValueError(f"relevant_ids[{index}] 必须是非空字符串")
        normalized.add(relevant_id)
    return normalized


def _top_doc_ids(docs, k):
    if k <= 0:
        raise ValueError("k 必须大于 0")
    ids = []
    for index, doc in enumerate(docs[:k]):
        doc_id = doc.get("id")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError(f"docs[{index}].id 必须是非空字符串")
        ids.append(doc_id)
    return ids


def recall_at_k(docs, relevant_ids, k):
    """Top-K 命中的 canonical chunk ID 占全部 relevant chunk IDs 的比例。"""
    relevant = _relevant_id_set(relevant_ids)
    retrieved = set(_top_doc_ids(docs, k))
    return len(retrieved & relevant) / len(relevant)


def hit_at_k(docs, relevant_ids, k):
    """Top-K 是否至少命中一个 relevant chunk（0/1）。"""
    relevant = _relevant_id_set(relevant_ids)
    retrieved = set(_top_doc_ids(docs, k))
    return 1.0 if retrieved & relevant else 0.0


def mrr_at_k(docs, relevant_ids, k=10):
    """前 K 位中第一个 relevant chunk 的倒数排名，无命中则为 0。"""
    relevant = _relevant_id_set(relevant_ids)
    for rank, doc_id in enumerate(_top_doc_ids(docs, k), 1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def score_retrieval_result(docs, relevant_ids):
    """对成功的检索响应评分；缺 ground truth 时明确标记为不可评分。"""
    if not relevant_ids:
        return {
            "status": "unscored",
            "reason": "missing_relevant_chunk_ids",
        }
    metrics = {
        "recall_at_5": recall_at_k(docs, relevant_ids, 5),
        "recall_at_10": recall_at_k(docs, relevant_ids, 10),
        "mrr_at_10": mrr_at_k(docs, relevant_ids, 10),
        "hit_rate_at_5": hit_at_k(docs, relevant_ids, 5),
    }
    return {
        "status": "empty" if not docs else "ok",
        "n": len(docs),
        "metrics": metrics,
    }


# ---------------------------------------------------------------- 生成层 judge

JUDGE_PROMPT = """你是 RAG 系统评测员。请对一次问答进行打分。

【用户问题】
{question}

【检索到的文档片段】
{docs}

【系统回答】
{answer}

请评估两个维度：
1. faithfulness（忠实度，1-5）：回答是否严格基于检索到的文档？是否编造了文档中没有的事实？（幻觉=低分）
2. relevance（相关性，1-5）：回答是否命中问题的核心要点？是否完整？
   注意：如果检索到的文档与问题无关，导致回答质量差，这属于检索问题，relevance 照常给低分，但 faithfulness 若回答确实忠于文档可给高分。

只输出 JSON，格式：{{"faithfulness": 整数1-5, "relevance": 整数1-5, "reason": "一句话理由（中文）"}}"""


def judge_one(question, docs, answer):
    """LLM-as-judge：忠实度 + 相关性"""
    doc_text = "\n---\n".join(d[:300] for d in docs) if docs else "（无检索结果）"
    raw = llm_chat([
        {"role": "system", "content": "你是严谨的评测员，只输出 JSON。"},
        {"role": "user", "content": JUDGE_PROMPT.format(question=question, docs=doc_text, answer=answer[:1500])},
    ])
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {"faithfulness": None, "relevance": None, "reason": f"judge 解析失败: {raw[:80]}"}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"faithfulness": None, "relevance": None, "reason": f"judge JSON 损坏: {raw[:80]}"}


# ---------------------------------------------------------------- 主流程

def evaluate_strategy(item, strategy, post=api_post):
    """评测单个检索策略，并把质量失败与执行失败分开。"""
    _, params, field = strategy
    relevant_ids = item.get("relevant_chunk_ids")
    if not relevant_ids:
        return {
            "status": "unscored",
            "reason": "missing_relevant_chunk_ids",
        }
    try:
        data = post(
            "/query/hybrid",
            {"question": item["question"], "top_k": 10, **params},
        )
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, dict) or field not in result:
            raise ValueError(f"API 响应缺少 result.{field}")
        docs = result[field]
        if not isinstance(docs, list):
            raise ValueError(f"API 响应 result.{field} 必须是列表")
        if params.get("use_reranker"):
            reranker_status = result.get("reranker_status")
            if not isinstance(reranker_status, dict):
                raise ValueError("API 响应缺少 result.reranker_status")
            mode = reranker_status.get("mode")
            if mode == "fallback":
                return {
                    "status": "fallback",
                    "reason": reranker_status.get("reason") or "unknown",
                    "n": len(docs),
                }
            if mode != "cross_encoder":
                raise ValueError(f"未知 reranker_status.mode: {mode!r}")
        return score_retrieval_result(docs, relevant_ids)
    except Exception as e:
        return {"status": "error", "reason": str(e)[:100]}


def run_retrieval(item, post=api_post):
    """单题检索层：三策略各跑一遍，返回带状态的指标。"""
    return {
        name: evaluate_strategy(item, strategy, post=post)
        for strategy in STRATEGIES
        for name in [strategy[0]]
    }


def run_generation(item):
    """单题生成层：完整问答链路 + judge"""
    try:
        data = api_post("/query", {"question": item["question"]})
        answer = data.get("answer", "")
        sources = data.get("sources", [])
        docs = [s.get("content", "") if isinstance(s, dict) else str(s) for s in sources]
        judge = judge_one(item["question"], docs, answer)
        return {
            "answer": answer[:500],
            "n_sources": len(sources),
            "faithfulness": judge.get("faithfulness"),
            "relevance": judge.get("relevance"),
            "reason": judge.get("reason", ""),
        }
    except Exception as e:
        return {"error": str(e)[:100]}


def avg(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 2) if vals else None


METRIC_NAMES = (
    "recall_at_5",
    "recall_at_10",
    "mrr_at_10",
    "hit_rate_at_5",
)


def aggregate_retrieval_results(question_results):
    """仅汇总真实评分项，并保留每种执行状态的计数。"""
    summary = {}
    for name, _, _ in STRATEGIES:
        counts = {
            "total": 0,
            "scored": 0,
            "ok": 0,
            "empty": 0,
            "error": 0,
            "unscored": 0,
            "fallback": 0,
        }
        values = {metric: [] for metric in METRIC_NAMES}
        for entry in question_results:
            outcome = entry.get("retrieval", {}).get(name)
            if not isinstance(outcome, dict):
                continue
            counts["total"] += 1
            status = outcome.get("status", "error")
            if status in counts:
                counts[status] += 1
            if status not in {"ok", "empty"}:
                continue
            counts["scored"] += 1
            metrics = outcome.get("metrics", {})
            for metric in METRIC_NAMES:
                value = metrics.get(metric)
                if isinstance(value, (int, float)):
                    values[metric].append(value)
        summary[name] = {
            "counts": counts,
            "metrics": {metric: avg(values[metric]) for metric in METRIC_NAMES},
        }
    return summary


def format_progress_status(inner_errors, fatal_error=None, notices=None):
    """生成可在 Windows GBK 等窄字符控制台安全输出的进度文本。"""
    if fatal_error:
        return f"ERROR {fatal_error[:40]}"
    if inner_errors:
        return "WARN " + "; ".join(inner_errors)
    if notices:
        return "; ".join(dict.fromkeys(notices))
    return "OK"


def result_output_message(path):
    return f"评测结果已写入 {path}"


def main():
    ap = argparse.ArgumentParser(description="RAGNEXUS 检索+生成评测")
    ap.add_argument("--set", default="eval/eval_set.json")
    ap.add_argument("--manifest", default="kb_v2/build/manifest.json")
    ap.add_argument("--out", default="eval/results.json")
    ap.add_argument(
        "--split",
        choices=("development", "heldout", "all"),
        default="development",
        help="默认只跑可调优的 development；heldout/all 需显式解锁",
    )
    ap.add_argument(
        "--allow-heldout",
        action="store_true",
        help="确认当前运行可以消费 heldout；冻结配置前不要使用",
    )
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--generation-only", action="store_true")
    ap.add_argument("--max-questions", type=int, default=0, help="只跑前 N 题（调试用）")
    args = ap.parse_args()

    try:
        evalset = load_and_validate_eval_set(args.set, args.manifest)
        items = select_questions(evalset, args.split, args.allow_heldout)
    except ValueError as exc:
        ap.error(str(exc))
    if args.max_questions:
        items = items[: args.max_questions]

    do_retrieval = not args.generation_only
    do_generation = not args.retrieval_only
    if do_generation and not DEEPSEEK_KEY:
        print("[warn] 未设置 DEEPSEEK_API_KEY，生成层评测不可用，降级为检索层")
        do_generation = False

    results = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "set": args.set, "manifest": args.manifest, "split": args.split,
               "n_questions": len(items),
               "questions": []}

    print(f"RAGNEXUS 评测 | {len(items)} 题 | 检索层={do_retrieval} 生成层={do_generation}")
    print("=" * 66)

    t0 = time.time()
    for i, item in enumerate(items, 1):
        qid = item.get("id", i)
        print(f"[{i}/{len(items)}] {item['question'][:44]}", end="", flush=True)
        entry = {"id": qid, "question": item["question"],
                 "category": item.get("category", ""), "split": item["split"]}
        inner_errors = []
        notices = []
        fatal_error = None
        try:
            if do_retrieval:
                entry["retrieval"] = run_retrieval(item)
                for name, _, _ in STRATEGIES:
                    r = entry["retrieval"].get(name, {})
                    if r.get("status") == "error":
                        inner_errors.append(f"{name}:{r.get('reason', '')[:60]}")
                    elif r.get("status") == "unscored":
                        notices.append(
                            f"UNSCORED {r.get('reason', 'missing_ground_truth')}"
                        )
                    elif r.get("status") == "fallback":
                        notices.append(
                            f"FALLBACK {name}:{r.get('reason', 'unknown')}"
                        )
            if do_generation:
                entry["generation"] = run_generation(item)
                if "error" in entry["generation"]:
                    inner_errors.append(f"gen:{entry['generation']['error'][:60]}")
        except Exception as e:
            entry["error"] = str(e)[:100]
            fatal_error = str(e)
        results["questions"].append(entry)
        status = format_progress_status(inner_errors, fatal_error, notices)
        print(f"  {status}", flush=True)

    retrieval_summary = aggregate_retrieval_results(results["questions"])
    results["retrieval_summary"] = retrieval_summary
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("=" * 66)
    print(f"耗时 {time.time()-t0:.0f}s，原始结果 -> {args.out}")

    # ---------------------------------------------------------- 汇总
    print("\n## 检索层对比")
    print(f"{'策略':<12}{'R@5':<8}{'R@10':<8}{'MRR@10':<9}{'Hit@5':<8}{'scored/total':<14}")
    print("-" * 59)
    for name, _, _ in STRATEGIES:
        item = retrieval_summary[name]
        metrics = item["metrics"]
        counts = item["counts"]
        if not counts["scored"]:
            print(
                f"{name:<12}（无可评分数据；"
                f"error={counts['error']} unscored={counts['unscored']} "
                f"fallback={counts['fallback']}）"
            )
            continue
        print(
            f"{name:<12}{metrics['recall_at_5']:<8}"
            f"{metrics['recall_at_10']:<8}{metrics['mrr_at_10']:<9}"
            f"{metrics['hit_rate_at_5']:<8}"
            f"{counts['scored']}/{counts['total']:<12}"
        )
        if counts["empty"] or counts["error"] or counts["unscored"] or counts["fallback"]:
            print(
                f"  状态：empty={counts['empty']} error={counts['error']} "
                f"unscored={counts['unscored']} fallback={counts['fallback']}"
            )

    if do_generation:
        print("\n## 生成层（LLM-as-judge，1-5 分）")
        fh = [e["generation"]["faithfulness"] for e in results["questions"]
              if "generation" in e and e["generation"].get("faithfulness") is not None]
        rl = [e["generation"]["relevance"] for e in results["questions"]
              if "generation" in e and e["generation"].get("relevance") is not None]
        print(f"faithfulness 平均: {avg(fh)} / 5   ({len(fh)} 题有效)")
        print(f"relevance    平均: {avg(rl)} / 5   ({len(rl)} 题有效)")
        low = [e for e in results["questions"] if "generation" in e
               and isinstance(e["generation"].get("relevance"), (int, float))
               and e["generation"]["relevance"] <= 2]
        if low:
            print(f"\n低分案例（relevance ≤ 2，共 {len(low)} 题）：")
            for e in low[:5]:
                print(f"  [{e['id']}] {e['question'][:40]}")
                print(f"      judge: {e['generation'].get('reason', '')[:80]}")

    print(f"\n{result_output_message(args.out)}")


if __name__ == "__main__":
    main()
