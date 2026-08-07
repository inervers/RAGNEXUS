#!/usr/bin/env python3
"""benchmark.py — /query/hybrid 检索层压测（零 LLM 成本）

并发打 /query/hybrid（检索层，与生产同口径 sparse_weight=2.0），
统计 QPS、成功率、延迟分位数（P50/P95/P99）。

用法:
  python eval/benchmark.py                          # 默认：并发 20，30 秒
  python eval/benchmark.py --concurrency 5 --duration 15
  python eval/benchmark.py --concurrency 1 --duration 10   # 单并发基线（真实延迟）

注意: 压测前把后端限流调高，否则全是 429：
  $env:RAG_RATE_LIMIT = "10000"; python rag_api.py

依赖: 仅标准库。服务需在线（localhost:8000），.env 提供 API key。
"""
import argparse
import json
import os
import statistics
import threading
import time
import urllib.error
import urllib.request


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


def main():
    ap = argparse.ArgumentParser(description="RAGNEXUS 检索层压测")
    ap.add_argument("--concurrency", type=int, default=20, help="并发数（默认 20）")
    ap.add_argument("--duration", type=int, default=30, help="压测时长秒（默认 30）")
    ap.add_argument("--api", default=os.getenv("RAGNEXUS_API", "http://localhost:8000"))
    args = ap.parse_args()

    load_env()
    api_key = os.getenv("RAG_API_KEY", "rag-secret-key-2024")
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }

    # 问题池：从评测集取前 10 题（真实查询分布），取不到用兜底
    qs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_set.json")
    questions = []
    try:
        with open(qs_path, encoding="utf-8") as f:
            eval_set = json.load(f)
        for item in eval_set[:10]:
            q = item.get("question") if isinstance(item, dict) else str(item)
            if q:
                questions.append(q)
    except Exception:
        pass
    if not questions:
        questions = ["什么是RAG", "混合检索为什么比单路检索更好", "如何缩小PyTorch镜像"]

    stats = {"ok": 0, "429": 0, "err": 0}
    latencies = []
    lock = threading.Lock()
    stop = time.time() + args.duration

    def fire(q):
        body = json.dumps({
            "question": q, "use_reranker": False,
            "sparse_weight": 2.0, "top_k": 10,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{args.api}/query/hybrid", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:
            return -1

    def worker():
        i = 0
        while time.time() < stop:
            q = questions[i % len(questions)]
            t0 = time.perf_counter()
            code = fire(q)
            dt = (time.perf_counter() - t0) * 1000
            with lock:
                if code == 200:
                    stats["ok"] += 1
                    latencies.append(dt)
                elif code == 429:
                    stats["429"] += 1
                else:
                    stats["err"] += 1
                    if stats["err"] <= 3:
                        print(f"  [错误] HTTP {code} q={q[:30]}")
            i += 1

    print(f"压测开始：并发 {args.concurrency}，{args.duration}s，"
          f"目标 {args.api}/query/hybrid（sparse_weight=2.0, top_k=10）")
    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(args.concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0

    total = stats["ok"] + stats["429"] + stats["err"]
    qps = stats["ok"] / elapsed if elapsed else 0
    ok_rate = stats["ok"] / total if total else 0
    print("\n==== 压测结果 ====")
    print(f"时长 {elapsed:.1f}s | 总请求 {total} | 成功 {stats['ok']} | "
          f"429 {stats['429']} | 错误 {stats['err']}")
    print(f"QPS(成功) {qps:.1f} | 成功率 {ok_rate:.1%}")
    if latencies:
        lat = sorted(latencies)
        pct = lambda p: lat[min(len(lat) - 1, int(len(lat) * p))]
        print(f"延迟(ms): mean {statistics.mean(lat):.0f} | "
              f"P50 {pct(0.5):.0f} | P95 {pct(0.95):.0f} | "
              f"P99 {pct(0.99):.0f} | max {lat[-1]:.0f}")
    if stats["429"]:
        print("!! 出现 429：后端限流没调高？用 $env:RAG_RATE_LIMIT = \"10000\" 重启后端再压")


if __name__ == "__main__":
    main()
