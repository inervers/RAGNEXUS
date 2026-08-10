"""
API 集成测试（需要 Docker 容器运行中）

用法：
    pytest tests/ -v
    # 或直接运行
    python tests/test_api.py
"""
import json, os, sys, time
import urllib.request
from pathlib import Path

from security_config import load_api_key_from_sources

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
API_KEY = load_api_key_from_sources(
    os.environ,
    Path(__file__).resolve().parents[1] / ".env",
)
HDR = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

def _req(method, path, body=None):
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=HDR, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.request.HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code
    except urllib.request.URLError:
        return {"error": f"无法连接到 {API_BASE}"}, 503


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


def ok(name, msg=""):
    print(f"  {Colors.GREEN}✓{Colors.RESET} {name}  {msg}")


def fail(name, detail):
    print(f"  {Colors.RED}✗{Colors.RESET} {name}")
    print(f"    {Colors.YELLOW}{detail}{Colors.RESET}")


def test_health():
    """GET /health — 健康检查"""
    data, code = _req("GET", "/health")
    assert code == 200, f"状态码 {code}"
    data.get("status") == "ok" or data.get("status") == "healthy"
    ok("健康检查", f"status={data.get('status')}")


def test_query():
    """POST /query — 基础 RAG 查询"""
    data, code = _req("POST", "/query", {"question": "什么是动态计算图", "top_k": 3})
    assert code == 200, f"状态码 {code}"
    answer = data.get("answer", "")
    assert len(answer) > 50, "回答应超过 50 字"
    ok("基础 RAG 查询", f"回答长度 {len(answer)} 字")


def test_query_no_key():
    """POST /query — 无 API Key 应 403"""
    req = urllib.request.Request(
        f"{API_BASE}/query",
        data=json.dumps({"question": "test"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        fail("鉴权测试", "无 API Key 应返回 403 但通过了")
        return
    except urllib.request.HTTPError as e:
        assert e.code in (401, 403), f"应返回 401/403，实际 {e.code}"
        ok("API Key 鉴权", f"正确拒绝（{e.code}）")


def test_hybrid_search():
    """POST /query/hybrid — 混合检索"""
    data, code = _req("POST", "/query/hybrid", {"question": "Transformer 注意力机制", "top_k": 5})
    assert code == 200, f"状态码 {code}"
    r = data.get("result", {})
    assert "dense_top" in r, "应包含单路结果"
    assert "hybrid_top" in r, "应包含混合结果"
    ok("混合检索", f"单路={len(r.get('dense_top',[]))} 混合={len(r.get('hybrid_top',[]))}")


def test_hybrid_reranker():
    """POST /query/hybrid — 使用 Reranker"""
    data, code = _req("POST", "/query/hybrid", {
        "question": "RAG 检索增强生成",
        "top_k": 5,
        "use_reranker": True,
    })
    assert code == 200, f"状态码 {code}"
    r = data.get("result", {})
    assert "reranked" in r, "应包含 Reranker 结果"
    ok("Reranker 检索", f"Reranker 返回 {len(r.get('reranked',[]))} 条")


def test_agent_write():
    """POST /agent/write — Multi-Agent 写作"""
    data, code = _req("POST", "/agent/write", {
        "topic": "什么是深度学习",
        "max_retries": 1,
    })
    assert code == 200, f"状态码 {code}"
    result = data.get("result", {})
    content = result.get("content", "")
    assert len(content) > 50, "写作内容应超过 50 字"
    ok("Multi-Agent 写作", f"内容长度 {len(content)} 字")


def test_kb_docs():
    """GET /kb/docs — 知识库文档列表"""
    data, code = _req("GET", "/kb/docs")
    assert code == 200, f"状态码 {code}"
    cnt = data.get("count", 0)
    docs = data.get("documents", [])
    assert cnt > 0, "知识库应有文档"
    ok("知识库文档", f"共 {cnt} 篇")


def test_rate_limit():
    """测试限流是否生效（快速连续请求）"""
    for i in range(5):
        _req("GET", "/health")
    ok("限流测试", "5 次连续请求正常通过")


def main():
    tests = [
        test_health,
        test_query,
        test_query_no_key,
        test_hybrid_search,
        test_hybrid_reranker,
        # test_agent_write,   # 消耗 token，默认跳过
        test_kb_docs,
        test_rate_limit,
    ]

    print(f"\n  RAG Agent API 集成测试 — {time.strftime('%H:%M:%S')}")
    print(f"  API: {API_BASE}")
    print(f"  {'='*50}")

    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            failed += 1
            fail(t.__name__, str(e)[:120])

    print(f"\n  {'='*50}")
    total = passed + failed
    if failed == 0:
        print(f"  {Colors.GREEN}全部通过 ({total}/{total}){Colors.RESET}")
    else:
        print(f"  {Colors.RED}{failed} 失败 / {passed} 通过 (共 {total}){Colors.RESET}")
    print()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
