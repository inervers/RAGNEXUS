"""
检索评测脚本：对比单路向量、混合RRF、混合+Reranker
"""
import json, os, urllib.request, sys
from pathlib import Path

from security_config import load_api_key_from_sources

API = "http://localhost:8000"
HDR = {
    "X-API-Key": load_api_key_from_sources(os.environ, Path(__file__).resolve().with_name(".env")),
    "Content-Type": "application/json",
}

QUERIES = [
    ("动态计算图",             ["动态计算图", "Define-by-Run", "PyTorch"]),
    ("Cross-Encoder 和 Bi-Encoder 的区别", ["Cross-Encoder", "Bi-Encoder", "两阶段", "reranker"]),
    ("Docker 镜像层缓存优化",  ["Docker", "层缓存", "Dockerfile", "镜像体积"]),
    ("RRF 融合公式",           ["RRF", "Reciprocal Rank Fusion", "BM25"]),
    ("如何减少 LLM 幻觉",      ["RAG", "检索增强", "幻觉", "知识库"]),
]

def recall_at_k(docs, keywords, k):
    top = docs[:k]
    hits = 0
    for d in top:
        t = (d.get("text", "") + " " + d.get("content", "")).lower()
        if any(kw.lower() in t for kw in keywords):
            hits += 1
    return hits / max(len(top), 1)

def query_hybrid(question, use_reranker):
    body = json.dumps({"question": question, "top_k": 10, "use_reranker": use_reranker}).encode("utf-8")
    req = urllib.request.Request(f"{API}/query/hybrid", data=body, headers=HDR, method="POST")
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read().decode("utf-8"))

print("=" * 70)
print(f"{'检索评测报告':>70}")
print(f"{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'):>70}")
print(f"知识库: 28篇 | 测试: {len(QUERIES)}题")
print("=" * 70)

stats = {"dense": [], "hybrid": [], "reranked": []}

for qi, (q, kw) in enumerate(QUERIES, 1):
    print(f"\n[Q{qi}] {q}")
    print(f"      期望: {', '.join(kw)[:50]}")
    print()

    for method, use_rr, field in [
        ("单路向量",      False, "dense_top"),
        ("混合+RRF",      False, "hybrid_top"),
        ("混合+Reranker", True,  "reranked"),
    ]:
        try:
            data = query_hybrid(q, use_rr)
            result = data.get("result", {})
            docs = result.get(field, [])

            if not docs:
                print(f"  {method:<14} 空")
                continue

            r5 = recall_at_k(docs, kw, 5)
            r10 = recall_at_k(docs, kw, 10)
            n = len(docs)

            key = "dense" if field == "dense_top" else ("hybrid" if field == "hybrid_top" else "reranked")
            stats[key].append((r5, r10))

            print(f"  {method:<14} R@5={r5:.2f}  R@10={r10:.2f}  返回={n}")
        except Exception as e:
            print(f"  {method:<14} 错误 {str(e)[:60]}")

print()
print("=" * 70)
print("汇总")
print(f"{'方法':<16} {'R@5平均':<10} {'R@10平均':<10} {'综合分':<10}")
print("-" * 50)

for name, key in [("单路向量", "dense"), ("混合+RRF", "hybrid"), ("混合+Reranker", "reranked")]:
    vals = stats[key]
    if vals:
        avg5 = round(sum(v[0] for v in vals) / len(vals), 2)
        avg10 = round(sum(v[1] for v in vals) / len(vals), 2)
    else:
        avg5 = avg10 = 0.0
    score = round((avg5 + avg10) / 2, 2)
    print(f"{name:<16} {avg5:<10} {avg10:<10} {score:<10}")

print("=" * 70)

best = sorted(stats.items(), key=lambda x: sum(v[1] for v in x[1]) if x[1] else 0, reverse=True)[0][0]
label_map = {"dense": "单路向量", "hybrid": "混合+RRF", "reranked": "混合+Reranker"}
print(f"\n结论：{label_map[best]} 在 Recall@10 上表现最优")
