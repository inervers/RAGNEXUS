# RAG Agent API

生产级 RAG 服务，集成 Hybrid Search、Cross-Encoder Reranker、Multi-Agent 编排。  
Docker 一键部署，带 Streamlit 可视化前端。

---

## 项目结构

```
rag-agent-api/
├── rag_api.py           ← FastAPI 服务（鉴权/限流/日志/RAG）
├── rag_advanced.py      ← 混合检索 + Reranker
├── rag_multiagent.py    ← Multi-Agent 工作流（研究员→写作者→审核员）
├── rag_app.py           ← Streamlit 前端
├── style.css            ← 前端样式
├── DESIGN.md            ← 设计系统文档
├── .streamlit/          ← Streamlit 主题配置
├── Dockerfile           ← 容器构建
├── docker-compose.yml   ← 一键部署
└── requirements.txt     ← 依赖清单
```

---

## 快速开始

### 本地运行

```powershell
# 1. 设置 API Key
$env:DEEPSEEK_API_KEY = "sk-your-key-here"

# 2. 启动 API 服务（默认 8000 端口）
python rag_api.py

# 3. 启动前端（另一个终端，默认 8501 端口）
streamlit run rag_app.py
```

### Docker 部署

```powershell
docker compose up -d --build
```

访问 `http://localhost:8000/health` 验证 API，打开 `http://localhost:8501` 使用前端。

---

## 功能模块

| 功能 | 说明 |
|------|------|
| **标准 RAG 问答** | Function Calling 驱动，自动检索知识库 + LLM 回答，支持 SSE 流式 |
| **混合检索** | 稠密向量（all-MiniLM-L6-v2）+ BM25 稀疏检索 + RRF 融合，覆盖语义相关与精确术语匹配 |
| **Reranker 精排** | Cross-Encoder 对粗筛结果重排序，修正 Bi-Encoder 的排序偏差 |
| **Multi-Agent 写作** | 研究员→写作者→审核员协作流水线，带持久化记忆与状态驱动机防止死循环 |
| **知识库管理** | Chrome 持久化，支持 .txt/.pdf 上传与结构化日志追踪 |

### 生产工程化

| 能力 | 实现 |
|------|------|
| API 鉴权 | X-API-Key 请求头校验，无 Key 返回 401 |
| 速率限制 | 滑动窗口限流（30次/分钟），超限返回 429 |
| 结构化日志 | 全链路 trace_id 追踪，JSON 格式写入文件 |
| Docker 部署 | Python 3.11-slim 镜像，持久化 chroma_db / 日志 / 模型缓存 |

---

## API 接口

| 接口 | 鉴权 | 说明 |
|------|------|------|
| `GET /health` | 免鉴权 | 健康检查 |
| `POST /query` | X-API-Key | 标准 RAG 问答 |
| `POST /query/stream` | X-API-Key | 流式问答（SSE） |
| `POST /query/hybrid` | X-API-Key | 混合检索，可选 Reranker |
| `POST /doc` | X-API-Key | 添加知识 |
| `GET /kb/docs` | X-API-Key | 获取知识库全部文档 |
| `POST /agent/write` | X-API-Key | Multi-Agent 写作流水线 |

### 测试示例

```powershell
# 混合检索（稠密 + BM25 + Reranker）
$body = '{"question":"What is PyTorch?","use_reranker":true}'
curl.exe -X POST http://localhost:8000/query/hybrid -H "Content-Type: application/json" -H "X-API-Key: rag-secret-key-2024" -d $body

# Multi-Agent 写作
$body = '{"topic":"PyTorch 动态计算图","max_retries":2}'
curl.exe -X POST http://localhost:8000/agent/write -H "Content-Type: application/json" -H "X-API-Key: rag-secret-key-2024" -d $body
```

---

## 环境变量

在 `.env` 中配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 必填 |
| `RAG_API_KEY` | API 鉴权密钥 | rag-secret-key-2024 |
| `RAG_RATE_LIMIT` | 每分钟最大请求数 | 30 |

---

## 技术栈

`Python 3.11` `FastAPI` `ChromaDB` `Sentence-Transformers` `BM25` `Cross-Encoder` `Streamlit` `Docker`

[→ GitHub](https://github.com/inervers/rag-agent-api)
