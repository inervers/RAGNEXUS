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
from collections.abc import Mapping
from pathlib import Path

import httpx
from fastmcp import FastMCP
from security_config import SecurityConfigError, load_api_key_from_sources

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


def _load_api_key(
    environ: Mapping[str, str] | None = None,
    env_path: Path | None = None,
) -> str:
    """Load an explicit MCP key, falling back only to the project's configured `.env`."""
    environ = os.environ if environ is None else environ
    env_path = env_path or Path(__file__).resolve().with_name(".env")
    try:
        return load_api_key_from_sources(
            environ,
            env_path,
            environment_names=("RAGNEXUS_API_KEY",),
            file_name="RAG_API_KEY",
        )
    except SecurityConfigError as exc:
        if str(exc).startswith("Missing required"):
            raise SecurityConfigError(
                "Missing required RAGNEXUS_API_KEY or project .env RAG_API_KEY"
            ) from exc
        raise


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
    response_trace = resp.headers.get("X-Trace-Id")
    if response_trace and "trace_id" not in data:
        data["trace_id"] = response_trace
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


def _error_payload(status: int, data: dict) -> dict:
    codes = {
        0: "connection_error",
        401: "missing_api_key",
        403: "invalid_api_key",
        429: "rate_limited",
    }
    return {
        "ok": False,
        "error": {
            "code": codes.get(status, "upstream_error"),
            "message": _friendly_error(status, data),
            "trace_id": data.get("trace_id"),
        },
    }


@mcp.tool()
def retrieve_knowledge(query: str, top_k: int = 5) -> dict:
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
        return _error_payload(status, data)

    result = data.get("result", {})
    selected = result.get("selected", [])
    stats = result.get("stats", {})
    trace = result.get("trace", {})
    trace_id = data.get("trace_id") or trace.get("trace_id")
    summary = (
        f"查询「{query}」检索到 {len(selected)} 条相关内容"
        if selected
        else f"知识库中未检索到与「{query}」相关的内容"
    )
    return {
        "ok": True,
        "summary": summary,
        "query": query,
        "strategy": trace.get("strategy", "hybrid"),
        "trace_id": trace_id,
        "chunks": [
            {
                "id": item.get("id", ""),
                "text": item.get("text", "").strip(),
                "rrf_score": item.get("rrf_score", 0),
            }
            for item in selected
        ],
        "stats": {
            "dense_count": stats.get("dense_count", 0),
            "sparse_count": stats.get("sparse_count", 0),
            "overlap": stats.get("overlap", 0),
        },
    }


@mcp.tool()
def kb_status() -> dict:
    """查看 RAGNEXUS 知识库概况：块数、可用工具、限流策略、版本。"""
    status, data = _call_api("/health")
    if status != 200:
        return _error_payload(status, data)
    return {
        "ok": True,
        "status": data.get("status", "unknown"),
        "version": data.get("version", "?"),
        "chunks": data.get("chunks", 0),
        "tools": data.get("tools", []),
        "rate_limit": data.get("rate_limit", "?"),
        "trace_id": data.get("trace_id"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAGNEXUS MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                        help="stdio 给本地客户端；http 走 streamable HTTP 远程调用")
    parser.add_argument("--port", type=int, default=8101, help="http 模式端口")
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)
    else:
        mcp.run(transport="stdio")
