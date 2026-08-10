"""验证 RAGNEXUS MCP server 的 streamable HTTP 生命周期与结构化契约。

前置：
    python mcp_server.py --transport http --port 8101

用法：
    python mcp_http_client_test.py --url http://127.0.0.1:8101/mcp
"""

from __future__ import annotations

import argparse
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp_client_test import configure_utf8_output


async def main(url: str) -> None:
    async with streamable_http_client(url) as (read, write, get_session_id):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "ragnexus"

            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "kb_status",
                "retrieve_knowledge",
            }

            status = await session.call_tool("kb_status", {})
            assert status.isError is not True
            assert status.structuredContent is not None
            assert status.structuredContent["ok"] is True
            assert status.structuredContent["trace_id"]

            result = await session.call_tool(
                "retrieve_knowledge", {"query": "混合检索", "top_k": 3}
            )
            assert result.isError is not True
            assert result.structuredContent is not None
            assert result.structuredContent["ok"] is True
            assert result.structuredContent["strategy"] == "hybrid"
            assert result.structuredContent["trace_id"]
            assert all(chunk["id"] for chunk in result.structuredContent["chunks"])
            assert get_session_id()

    print("MCP streamable HTTP 验证通过：initialize → tools/list → tools/call")


if __name__ == "__main__":
    configure_utf8_output()
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8101/mcp")
    args = parser.parse_args()
    asyncio.run(main(args.url))
