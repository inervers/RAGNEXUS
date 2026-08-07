"""最小 MCP 客户端：验证 RAGNEXUS MCP server（stdio 模式）。

演示 MCP 协议完整生命周期：initialize 握手 → tools/list 发现工具 → tools/call 调用。
不依赖任何 GUI 客户端，纯 Python 跑通即证明 MCP 链路 OK。

用法（后端 8000 在跑的前提下）：
    python mcp_client_test.py

输出四步，全部 OK 即验证通过。
"""

from __future__ import annotations

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_CMD = ["python", "C:/Users/inervers/Desktop/OH-WorkSpace/RAGNEXUS/mcp_server.py"]
TEST_QUERY = "混合检索"

# 保险：强制子进程输出 UTF-8，避免 Windows 按 GBK 编码中文污染协议流
SERVER_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


async def main() -> None:
    params = StdioServerParameters(command=SERVER_CMD[0], args=SERVER_CMD[1:], env=SERVER_ENV)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. initialize 握手：客户端和服务端交换协议版本与能力
            init = await session.initialize()
            print(f"[1] initialize OK: server={init.serverInfo.name} v{init.serverInfo.version}")

            # 2. tools/list：发现服务端暴露的工具
            tools = await session.list_tools()
            print(f"[2] tools/list OK: {len(tools.tools)} 个工具")
            for t in tools.tools:
                print(f"    - {t.name}")

            # 3. tools/call：调用 kb_status（走 /health，验证连通性）
            status = await session.call_tool("kb_status", {})
            print(f"[3] call kb_status -> {status.content[0].text}")

            # 4. tools/call：调用 retrieve_knowledge（走 /query/hybrid，验证鉴权+检索）
            result = await session.call_tool(
                "retrieve_knowledge", {"query": TEST_QUERY, "top_k": 3}
            )
            text = result.content[0].text
            print(f"[4] call retrieve_knowledge('{TEST_QUERY}') -> {len(text)} 字符")
            print("---- 返回内容（前 500 字）----")
            print(text[:500])

    print("\n✅ MCP 链路验证通过：initialize → tools/list → tools/call 全部 OK")


if __name__ == "__main__":
    asyncio.run(main())
