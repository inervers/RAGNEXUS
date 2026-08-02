#!/usr/bin/env python3
"""RAGNEXUS 评测体系 v2：检索层 + 生成层双评测

对比三路检索策略（单路向量 / 混合+RRF / 混合+Reranker），
并对完整问答链路做 LLM-as-judge 打分（忠实度 + 相关性）。

用法:
  python eval_rag.py                           # 全量评测（检索层 + 生成层）
  python eval_rag.py --retrieval-only          # 只跑检索层（快，不调生成）
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
import urllib.request
from datetime import datetime

# ---------------------------------------------------------------- 配置

API = os.getenv("RAGNEXUS_API", "http://localhost:8000")
API_KEY = os.getenv("RAG_API_KEY", "rag-secret-key-2024")
LLM_BASE = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")

HDR = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# 检索策略 -> (/query/hybrid 参数, 结果字段)
STRATEGIES = [
    ("dense",    {"use_reranker": False}, "dense_top"),
    ("hybrid",   {"use_reranker": False}, "hybrid_top"),
    ("reranked", {"use_reranker": True},  "reranked"),
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

def api_post(path, body, timeout=90):
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers=HDR,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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

def recall_at_k(docs, keywords, k):
    """top-k 中命中任一关键词的文档占比（允许一个文档命中多次，归一化按 min(k, len)）"""
    top = docs[:k]
    if not top:
        return 0.0
    hits = 0
    for d in top:
        text = (d.get("text") or d.get("document") or "").lower()
        if any(kw.lower() in text for kw in keywords):
            hits += 1
    return hits / min(k, len(top))


def hit_at_k(docs, keywords, k):
    """top-k 中是否存在至少一个相关文档（0/1）"""
    return 1.0 if recall_at_k(docs, keywords, k) > 0 else 0.0


def mrr(docs, keywords):
    """第一个相关文档的倒数排名，无则 0"""
    for i, d in enumerate(docs, 1):
        text = (d.get("text") or d.get("document") or "").lower()
        if any(kw.lower() in text for kw in keywords):
            return 1.0 / i
    return 0.0


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

def run_retrieval(item):
    """单题检索层：三策略各跑一遍，返回指标"""
    out = {}
    for name, params, field in STRATEGIES:
        try:
            data = api_post("/query/hybrid",
                            {"question": item["question"], "top_k": 10, **params})
            docs = data.get("result", {}).get(field, []) or []
            kws = item.get("expected_keywords", [])
            out[name] = {
                "recall5": recall_at_k(docs, kws, 5),
                "recall10": recall_at_k(docs, kws, 10),
                "hit5": hit_at_k(docs, kws, 5),
                "mrr": mrr(docs, kws),
                "n": len(docs),
            }
        except Exception as e:
            out[name] = {"error": str(e)[:100]}
    return out


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


def main():
    ap = argparse.ArgumentParser(description="RAGNEXUS 检索+生成评测")
    ap.add_argument("--set", default="eval/eval_set.json")
    ap.add_argument("--out", default="eval/results.json")
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--generation-only", action="store_true")
    ap.add_argument("--max-questions", type=int, default=0, help="只跑前 N 题（调试用）")
    args = ap.parse_args()

    with open(args.set, encoding="utf-8") as f:
        evalset = json.load(f)
    items = evalset["questions"] if isinstance(evalset, dict) else evalset
    if args.max_questions:
        items = items[: args.max_questions]

    do_retrieval = not args.generation_only
    do_generation = not args.retrieval_only
    if do_generation and not DEEPSEEK_KEY:
        print("[warn] 未设置 DEEPSEEK_API_KEY，生成层评测不可用，降级为检索层")
        do_generation = False

    results = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "set": args.set, "n_questions": len(items),
               "questions": []}

    print(f"RAGNEXUS 评测 | {len(items)} 题 | 检索层={do_retrieval} 生成层={do_generation}")
    print("=" * 66)

    t0 = time.time()
    for i, item in enumerate(items, 1):
        qid = item.get("id", i)
        print(f"[{i}/{len(items)}] {item['question'][:44]}", end="", flush=True)
        entry = {"id": qid, "question": item["question"], "category": item.get("category", "")}
        inner_errors = []
        try:
            if do_retrieval:
                entry["retrieval"] = run_retrieval(item)
                for name, _, _ in STRATEGIES:
                    r = entry["retrieval"].get(name, {})
                    if "error" in r:
                        inner_errors.append(f"{name}:{r['error'][:60]}")
            if do_generation:
                entry["generation"] = run_generation(item)
                if "error" in entry["generation"]:
                    inner_errors.append(f"gen:{entry['generation']['error'][:60]}")
            ok = "✓"
            if inner_errors:
                ok = "⚠ " + "; ".join(inner_errors)
        except Exception as e:
            entry["error"] = str(e)[:100]
            ok = f"✗ {str(e)[:40]}"
        results["questions"].append(entry)
        print(f"  {ok}", flush=True)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("=" * 66)
    print(f"耗时 {time.time()-t0:.0f}s，原始结果 -> {args.out}")

    # ---------------------------------------------------------- 汇总
    print("\n## 检索层对比")
    agg = {name: {"r5": [], "r10": [], "mrr": [], "hit5": []} for name, _, _ in STRATEGIES}
    for e in results["questions"]:
        for name, _, _ in STRATEGIES:
            r = e.get("retrieval", {}).get(name, {})
            if "error" not in r:
                agg[name]["r5"].append(r["recall5"])
                agg[name]["r10"].append(r["recall10"])
                agg[name]["mrr"].append(r["mrr"])
                agg[name]["hit5"].append(r["hit5"])

    print(f"{'策略':<12}{'R@5':<8}{'R@10':<8}{'MRR':<8}{'Hit@5':<8}")
    print("-" * 44)
    for name, _, _ in STRATEGIES:
        a = agg[name]
        if not a["r5"]:
            print(f"{name:<12}（无数据）")
            continue
        print(f"{name:<12}{avg(a['r5']):<8}{avg(a['r10']):<8}{avg(a['mrr']):<8}{avg(a['hit5']):<8}")

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

    print("\n汇总已写入 eval/results.md（如存在）")


if __name__ == "__main__":
    main()
