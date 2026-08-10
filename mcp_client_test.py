"""最小 MCP 客户端：验证 RAGNEXUS MCP server（stdio 模式）。

演示 MCP 协议完整生命周期：initialize 握手 → tools/list 发现工具 → tools/call 调用。
不依赖任何 GUI 客户端，纯 Python 跑通即证明 MCP 链路 OK。

用法（后端 8000 在跑的前提下）：
    python mcp_client_test.py

输出四步，全部 OK 即验证通过。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from mcp.types import LATEST_PROTOCOL_VERSION

TEST_QUERY = "混合检索"

# 保险：强制子进程输出 UTF-8，避免 Windows 按 GBK 编码中文污染协议流
SERVER_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def configure_utf8_output() -> None:
    """让客户端自身日志与 MCP 子进程统一使用 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def server_command() -> tuple[str, list[str]]:
    server_path = Path(__file__).resolve().with_name("mcp_server.py")
    return sys.executable, [str(server_path)]


def start_server_process() -> subprocess.Popen[str]:
    command, args = server_command()
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [command, *args],
        cwd=Path(args[0]).parent,
        env=SERVER_ENV,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        bufsize=1,
        creationflags=creation_flags,
    )


def close_server_process(
    process: subprocess.Popen[str],
    timeout: float = 2.0,
) -> None:
    """只回收本客户端持有的精确子进程，兼容 Windows stdio EOF 异常。"""
    if process.stdin and not process.stdin.closed:
        process.stdin.close()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def _send(process: subprocess.Popen[str], message: dict) -> None:
    if not process.stdin:
        raise RuntimeError("MCP server stdin 不可用")
    process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    process.stdin.flush()


def _request(
    process: subprocess.Popen[str],
    request_id: int,
    method: str,
    params: dict | None = None,
) -> dict:
    _send(
        process,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
    )
    if not process.stdout:
        raise RuntimeError("MCP server stdout 不可用")
    while True:
        line = process.stdout.readline()
        if not line:
            detail = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"MCP server 提前退出：{detail[-500:]}")
        response = json.loads(line)
        if response.get("id") != request_id:
            continue
        if "error" in response:
            raise RuntimeError(f"MCP JSON-RPC error: {response['error']}")
        return response["result"]


def main() -> None:
    process = start_server_process()
    try:
        init = _request(
            process,
            1,
            "initialize",
            {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ragnexus-smoke", "version": "1.0"},
            },
        )
        server_info = init["serverInfo"]
        print(f"[1] initialize OK: server={server_info['name']} v{server_info['version']}")

        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        tools = _request(process, 2, "tools/list")
        tool_names = {tool["name"] for tool in tools["tools"]}
        assert tool_names == {"kb_status", "retrieve_knowledge"}, tool_names
        print(f"[2] tools/list OK: {len(tools['tools'])} 个工具")
        for tool in tools["tools"]:
            print(f"    - {tool['name']}")

        status = _request(
            process,
            3,
            "tools/call",
            {"name": "kb_status", "arguments": {}},
        )
        assert status.get("isError") is not True
        status_data = status["structuredContent"]
        assert status_data["ok"] is True
        assert status_data["trace_id"]
        print(f"[3] call kb_status -> {status['content'][0]['text']}")

        result = _request(
            process,
            4,
            "tools/call",
            {
                "name": "retrieve_knowledge",
                "arguments": {"query": TEST_QUERY, "top_k": 3},
            },
        )
        assert result.get("isError") is not True
        result_data = result["structuredContent"]
        assert result_data["ok"] is True
        assert result_data["strategy"] == "hybrid"
        assert result_data["trace_id"]
        assert all(chunk["id"] for chunk in result_data["chunks"])
        text = result["content"][0]["text"]
        print(f"[4] call retrieve_knowledge('{TEST_QUERY}') -> {len(text)} 字符")
        print("---- 返回内容（前 500 字）----")
        print(text[:500])
    finally:
        close_server_process(process)

    print("\n✅ MCP 链路验证通过：initialize → tools/list → tools/call 全部 OK")


if __name__ == "__main__":
    configure_utf8_output()
    main()
