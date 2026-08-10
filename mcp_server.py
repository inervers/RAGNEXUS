"""RAGNEXUS MCP Server：把生产 RAG 服务的混合检索暴露为 MCP 工具。

架构：MCP 客户端（Claude / Cursor / Codex）
          → stdio 或 streamable HTTP
          → 本 server（薄壳，检索逻辑零改动）
          → HTTP → RAGNEXUS API（复用鉴权 / 限流 / trace 全链路日志）

传输模式：
    stdio（默认，本地客户端）：
        python mcp_server.py
    streamable HTTP（远程调用）：
        python mcp_server.py --transport http --port 8101

环境变量：
    RAGNEXUS_API_KEY   必填。RAGNEXUS 的 X-API-Key。
    RAGNEXUS_BASE_URL  可选，默认 http://127.0.0.1:8000

工具：
    retrieve_knowledge(query, top_k)  混合检索（dense + BM25 + RRF），返回片段
    kb_status()                       知识库概况（块数 / 工具 / 限流 / 版本）
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

import httpx
from fastmcp import FastMCP
from retrieval_service import format_trace_summary

# stdio 模式下 stdout 是 MCP 协议通道，只能传 JSON-RPC。
# 强制 UTF-8，并把一切日志/提示打到 stderr，避免污染协议流（Windows 下默认
# 会按 GBK 编码中文，客户端按 UTF-8 解码直接崩，报 UnicodeDecodeError）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _log(msg: str) -> None:
    """所有非协议输出走 stderr，MCP 客户端会忽略或转发为日志。"""
    print(msg, file=sys.stderr, flush=True)

BASE_URL = os.environ.get("RAGNEXUS_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 30.0


def _load_api_key() -> str:
    """API Key 优先级：环境变量 RAGNEXUS_API_KEY > 脚本同目录 .env 的 RAG_API_KEY > 后端默认值。

    注意：RAGNEXUS 本地跑 rag_api.py 时并不加载 .env（只有 docker compose 通过
    env_file 注入），所以本地后端实际用的很可能是默认 key rag-secret-key-2024。
    这里直接从脚本同目录 .env 读取，保证与后端配置一致，零额外配置。
    """
    env_key = os.environ.get("RAGNEXUS_API_KEY")
    if env_key:
        return env_key

    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "RAG_API_KEY":
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return "rag-secret-key-2024"  # 与 rag_api.py 默认值一致


API_KEY = _load_api_key()

mcp = FastMCP(
    "ragnexus",
    instructions=(
        "RAGNEXUS 是个人知识库 RAG 服务（dense + BM25 + RRF 混合检索）。"
        "检索用户知识库请用 retrieve_knowledge；想先了解知识库规模用 kb_status。"
        "查询用自然语言提问即可。"
    ),
)


def _call_api(path: str, payload: dict | None = None) -> tuple[int, dict]:
    """调 RAGNEXUS API，带鉴权与 trace header。返回 (status_code, json)。"""
    headers = {"X-Trace-Id": uuid.uuid4().hex}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    try:
        if payload is not None:
            resp = httpx.post(f"{BASE_URL}{path}", json=payload, headers=headers, timeout=TIMEOUT)
        else:
            resp = httpx.get(f"{BASE_URL}{path}", headers=headers, timeout=TIMEOUT)
    except httpx.ConnectError:
        return 0, {"error": f"无法连接 RAGNEXUS（{BASE_URL}），请先启动服务"}
    except httpx.TimeoutException:
        return 0, {"error": "RAGNEXUS 请求超时"}
    try:
        data = resp.json()
    except Exception:
        data = {"error": f"非 JSON 响应（HTTP {resp.status_code}）"}
    return resp.status_code, data


def _friendly_error(status: int, data: dict) -> str:
    """把 RAGNEXUS 的 HTTP 错误转成对 MCP 客户端友好的文本。"""
    if status == 401:
        return "RAGNEXUS 鉴权失败：缺少 API Key。请在 MCP 配置 env 里设置 RAGNEXUS_API_KEY。"
    if status == 403:
        return "RAGNEXUS 鉴权失败：API Key 无效。请检查 RAGNEXUS_API_KEY 与后端配置一致。"
    if status == 429:
        return "RAGNEXUS 限流：超过 30 次/分钟，请稍后重试。"
    if status == 0:
        return data.get("error", "网络错误")
    err = data.get("error") or data.get("detail") or f"HTTP {status}"
    trace_id = data.get("trace_id")
    return f"RAGNEXUS 错误：{err}" + (f"（trace_id={trace_id}）" if trace_id else "")


@mcp.tool()
def retrieve_knowledge(query: str, top_k: int = 5) -> str:
    """从 RAGNEXUS 知识库做混合检索（稠密向量 + BM25 + RRF 融合）。

    Args:
        query: 自然语言问题，例如「什么是混合检索」
        top_k: 返回片段数，1-10，默认 5
    """
    top_k = max(1, min(10, int(top_k)))
    status, data = _call_api(
        "/query/hybrid",
        {"question": query, "top_k": top_k, "strategy": "hybrid"},
    )

    if status != 200:
        return _friendly_error(status, data)

    result = data.get("result", {})
    hybrid = result.get("hybrid_top", [])
    stats = result.get("stats", {})
    if not hybrid:
        return (
            f"知识库中未检索到与「{query}」相关的内容"
            f"（dense={stats.get('dense_count', 0)} 条，"
            f"sparse={stats.get('sparse_count', 0)} 条）。\n"
            f"（{format_trace_summary(result)}）"
        )

    lines = [f"查询「{query}」检索到 {len(hybrid)} 条相关内容：", ""]
    for item in hybrid:
        lines.append(f"[{item.get('id', '?')}] rrf={item.get('rrf_score', 0)}")
        lines.append(item.get("text", "").strip())
        lines.append("")
    lines.append(f"（dense {stats.get('dense_count', 0)} 条 / BM25 {stats.get('sparse_count', 0)} 条 / 重叠 {stats.get('overlap', 0)}）")
    lines.append(f"（{format_trace_summary(result)}）")
    return "\n".join(lines)


@mcp.tool()
def kb_status() -> str:
    """查看 RAGNEXUS 知识库概况：块数、可用工具、限流策略、版本。"""
    status, data = _call_api("/health")
    if status != 200:
        return _friendly_error(status, data)
    return (
        f"RAGNEXUS {data.get('version', '?')}：知识库 {data.get('chunks', 0)} 块，"
        f"工具 {', '.join(data.get('tools', []))}，限流 {data.get('rate_limit', '?')}/分钟"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAGNEXUS MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                        help="stdio 给本地客户端；http 走 streamable HTTP 远程调用")
    parser.add_argument("--port", type=int, default=8101, help="http 模式端口")
    args = parser.parse_args()

    if API_KEY == "rag-secret-key-2024":
        _log("[warn] 使用后端默认鉴权 key（rag-secret-key-2024）。若后端 .env 改过 RAG_API_KEY，请设置 RAGNEXUS_API_KEY 覆盖。")

    if args.transport == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)
    else:
        mcp.run(transport="stdio")
