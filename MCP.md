# RAGNEXUS MCP Server

把 RAGNEXUS 的混合检索暴露为标准 MCP 工具，任何 MCP 客户端（Claude Desktop / Cursor / Codex / 其他支持 MCP 的 Agent）都能直接检索知识库。

**设计原则：MCP server 是纯薄壳，检索逻辑零改动。** 内部走 HTTP 调 RAGNEXUS 自家 API，复用后端的鉴权（X-API-Key）、限流（30 次/分钟）、trace_id 全链路日志。协议层由官方 SDK 生态（fastmcp，底层 `mcp` 包）实现。

```
MCP 客户端 ──tools/list──► mcp_server.py ──HTTP──► RAGNEXUS API
  Claude    ──tools/call─► (FastMCP 薄壳)  X-API-Key   /query/hybrid
  Cursor                              trace_id    /health
  Codex                                           鉴权/限流/日志
```

## 安装

```powershell
pip install -i https://mirrors.aliyun.com/pypi/simple/ fastmcp
```

依赖：`fastmcp`（内部依赖 `mcp`、`httpx`、`pydantic`，RAGNEXUS 后端已用 httpx，无需另装）。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `RAGNEXUS_API_KEY` | 否 | 覆盖 API Key（优先级最高，留给 Cursor 等客户端注入）。**不设时自动读脚本同目录 `.env` 的 `RAG_API_KEY`，再兜底后端默认值 `rag-secret-key-2024`** |
| `RAGNEXUS_BASE_URL` | 否 | 默认 `http://127.0.0.1:8000` |

**Key 自动发现逻辑**（与后端 rag_api.py 的 `RAG_API_KEY` 对齐）：
1. 环境变量 `RAGNEXUS_API_KEY`（客户端注入优先）
2. 脚本同目录 `.env` 里的 `RAG_API_KEY`（与后端共享同一配置源）
3. 后端默认值 `rag-secret-key-2024`

注意：RAGNEXUS 本地跑 `python rag_api.py` 时**不会加载 .env**（只有 docker compose 用 `env_file` 注入），所以本地后端实际用的很可能就是默认 key。若后端改过 key，在 MCP 配置里显式设 `RAGNEXUS_API_KEY` 即可。

## 启动

本地 stdio（给 Claude Desktop / Cursor / Codex）：

```powershell
python mcp_server.py
```

远程 streamable HTTP：

```powershell
python mcp_server.py --transport http --port 8101
```

前提：RAGNEXUS 后端已启动（`python rag_api.py` 或 docker compose）。Key 自动从 `.env` 读取，零配置。

## 验证

**方式一：MCP Inspector（图形化，推荐）**

```powershell
npx @modelcontextprotocol/inspector python mcp_server.py
```

浏览器打开后：Tools 面板应看到 `retrieve_knowledge`、`kb_status`；手动调用 `kb_status` 应返回知识库概况；调用 `retrieve_knowledge` 传真实问题应返回片段。

**方式二：直接跑（冒烟）**

```powershell
python mcp_server.py   # 无报错即可；再配合 Inspector 验证工具调用
```

## 接入客户端

### Cursor

Settings → MCP → Add new MCP server：

```json
{
  "mcpServers": {
    "ragnexus": {
      "command": "python",
      "args": ["C:/Users/inervers/Desktop/OH-WorkSpace/RAGNEXUS/mcp_server.py"],
      "env": { "RAGNEXUS_API_KEY": "<你的 key>" }
    }
  }
}
```

启用后在对话里直接问"从我的知识库里查一下 XXX"，观察它是否调用 `retrieve_knowledge`。

### Claude Desktop

`claude_desktop_config.json` 的 `mcpServers` 节点，结构同上（command/args/env）。

### Codex（API 模式）

已在 `~/.codex/config.toml` 注册（`[mcp_servers.ragnexus]`，command=python + PYTHONIOENCODING=utf-8），**实测通过**：Codex 新会话可见 retrieve_knowledge/kb_status 工具，能直接检索知识库。Key 不写入配置（server 自动从 .env 读）。

前提：RAGNEXUS 后端 8000 在跑。

## 工具清单

| 工具 | 参数 | 说明 |
|---|---|---|
| `retrieve_knowledge` | `query: str`, `top_k: int = 5` | 混合检索（dense + BM25 + RRF），返回片段 + rrf 分数 + 统计 |
| `kb_status` | 无 | 知识库块数 / 工具 / 限流 / 版本（走 `/health`，无需鉴权） |

设计取舍：
- **只读不写**：暂不暴露 add/delete 工具。写操作会让 MCP 客户端拥有改动知识库的能力，先不做（面试可讲"权限最小化"）。
- **错误可诊断**：401/403/429/连接失败都有明确中文提示，429 会说明限流窗口，后端错误带 trace_id 便于对日志。

## 面试要点

1. **架构一句话**：MCP server 是协议壳，业务逻辑全在 RAGNEXUS 后端，鉴权/限流/日志全部复用，零重复实现。
2. **协议生命周期**：客户端 `initialize` 握手 → `tools/list` 发现工具 → `tools/call` 调用；JSON-RPC 2.0 消息。
3. **传输模式**：stdio（本地进程，环境变量注入 Key）vs streamable HTTP（远程，可走已有安全层）。
4. **2025-11-25 新规范**：stateless core（服务端无状态，会话状态归客户端管理）、Tasks（长时间运行任务的标准化抽象）、Authorization 规范（OAuth 2.1 风格授权）。
5. **为什么走 HTTP 而非 import 直调**：RAGNEXUS 已是独立服务，复用其鉴权/限流/观测；MCP server 换机器部署不用改。

## 踩坑记录（面试素材）

**stdio 模式 stdout 是协议通道**：MCP stdio 规定 stdout 只能传 JSON-RPC 消息，任何非协议输出都会污染协议流。

- 现象：客户端报 `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd3`
- 根因：server 把 warn 打在 stdout，Windows 下 Python 对管道按系统编码（GBK）编码中文，客户端按 UTF-8 解析直接崩
- 修复：所有日志/提示走 `stderr` + `sys.stdout.reconfigure(encoding="utf-8")` 双保险
- 通用规则：MCP server 里 **stdout 只属于协议**，人类可读的输出一律 stderr

## 后续扩展（可选）

- 暴露 `add_document` / `list_documents` 写工具（需要权限设计）
- HTTP 模式挂到公网/内网网关，复用 Nginx 的 TLS
- 用官方裸 `mcp` SDK 重写（当前是 fastmcp 封装），展示"协议层理解"
