# RAGNEXUS

生产级 RAG 服务，集成 Hybrid Search、Cross-Encoder Reranker、Multi-Agent 编排。
终端风格 React 前端（4-tab），Docker 一键部署（后端 8000 + 前端 8080）。

---

## 项目结构

```
RAGNEXUS/
├── rag_api.py           ← FastAPI 服务（鉴权/限流/日志/RAG/SSE 流式）
├── rag_advanced.py      ← 混合检索 + Reranker
├── rag_multiagent.py    ← Multi-Agent 工作流（研究员→写作者→审核员）
├── frontend/            ← React 前端（4-tab 终端风格）
│   ├── src/App.tsx      ← 问答 / 混合检索 / 知识库 / Agent 写作
│   ├── vite.config.ts   ← dev 代理（/health|/query|/doc|/kb|/agent → 8000）
│   ├── nginx.conf       ← 部署转发 + SSE buffering 关闭
│   ├── Dockerfile       ← node:20-alpine 构建 → nginx:alpine 托管
│   └── public/design-showcase.html ← 设计展示页（特效 + 后端实时数据）
├── docs-site/           ← 静态文档站（4 页，已发布 GitHub Pages）
├── rag_app.py           ← 遗留 Streamlit 前端（已弃用，主力前端见 frontend/）
├── pdf_parser.py        ← PDF 解析
├── ocr_client.py        ← 百度 OCR（扫描件识别）
├── docs/OPS-NOTES.md    ← 运维笔记（踩坑手册，遇到问题先看这里）
├── Dockerfile           ← 后端容器构建
├── docker-compose.yml   ← 一键部署
└── requirements.txt     ← 依赖清单
```

---

## 快速开始

### 本地运行

```powershell
# 1. 配置环境变量（.env：DEEPSEEK_API_KEY 必填，ZHIPU_API_KEY 可选 fallback）
# 2. 启动 API 服务（默认 8000 端口）
python rag_api.py

# 3. 启动前端 dev server（另一个终端，默认 5173 端口）
cd frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`（vite dev 已配置代理转发到 8000）。

### Docker 部署

```powershell
# 国内网络：先开代理手动拉基础镜像（BuildKit 的 FROM 不继承 pull 代理）
docker pull node:20-alpine
docker pull nginx:alpine

# 构建并启动全部服务
docker compose up -d --build
```

启动后：
- 前端 → `http://localhost:8080`（nginx 托管，同源请求转发到 API）
- API 服务 → `http://localhost:8000`
- 前端 API 走同源（`API_BASE=""`），由 nginx 正则转发 `/health|/query|/doc|/kb|/agent`，无需跨域配置

> ⚠️ 镜像构建细节（npm ci 崩溃、npmmirror 直连、.dockerignore 优化）见 [docs/OPS-NOTES.md](docs/OPS-NOTES.md)。

### Agent 记忆持久化

Agent 的写作记忆保存在本地 `memory/` 目录，容器重建后记忆不丢失。

---

## 功能模块

| 功能 | 说明 |
|------|------|
| **标准 RAG 问答** | Function Calling 驱动，自动检索知识库 + LLM 回答，SSE 流式 + 打字动画 + 取消 |
| **混合检索** | 稠密向量（all-MiniLM-L6-v2）+ BM25 稀疏检索 + RRF 融合，覆盖语义相关与精确术语匹配 |
| **Reranker 精排** | Cross-Encoder 对粗筛结果重排序，修正 Bi-Encoder 的排序偏差 |
| **Multi-Agent 写作** | 研究员→写作者→审核员协作流水线，带持久化记忆与评分/重试循环 |
| **知识库管理** | 支持 .txt/.pdf 拖拽上传，PDF 实时预览（/doc/preview），分页浏览与跳页 |

前端为终端风格 4-tab 布局：问答 / 混合检索 / 知识库 / Agent 写作，支持暗色主题与 localStorage 会话持久化。

### 生产工程化

| 能力 | 实现 |
|------|------|
| API 鉴权 | X-API-Key 请求头校验，无 Key 返回 401 |
| 速率限制 | 滑动窗口限流（30次/分钟），超限返回 429 |
| 结构化日志 | 全链路 trace_id 追踪，JSON 格式写入文件 |
| Docker 部署 | 后端 Python 镜像 + 前端 nginx 镜像，双容器编排 |
| SSE 流式 | 后端 X-Accel-Buffering: no + nginx proxy_buffering off |

---

## 展示页与文档站

### 设计展示页（`frontend/public/design-showcase.html`）

单文件设计原型，深色数据工作台风格，用于演示产品视觉与交互：

- 特效：PixelTrail 像素拖尾 + 点击爆散、星链交互图（长按中心节点可沿网络自由拖动，节点处拐弯）、BlurText 标题逐字模糊入场、磁吸按钮、3D 倾斜卡片
- 打开方式：双击文件（file:// 协议自适应）或 `npm run dev` 后访问 `/design-showcase.html`
- **后端实时数据接入**：页面自动读取正式应用接口（`/health`、`/kb/docs`、`/query/hybrid`），状态卡、指标条、知识库文档列表、检索管线图全部显示真实数据；后端离线时自动降级为"未连接"提示

### 静态文档站（`docs-site/`）

零依赖静态站（概览 / 快速开始 / API / 设计取舍 4 页），与前端同款设计语言，已发布到 GitHub Pages：

<https://inervers.github.io/RAGNEXUS/>

更新方式：`git subtree push --prefix docs-site origin gh-pages`

---

## 设计取舍（面试向）

> 这部分记录了项目中的关键技术决策和背后思考，面试官问"为什么选这个不选那个"时，答案就在这里。

### 为什么用 DeepSeek 而不是 OpenAI / Claude？

**不是情怀，是现实考量。**
- 成本：DeepSeek API 价格约为 GPT-4 的 1/20，在大量 Agent 调用场景下差距显著
- 中文能力：在中英混合的技术文档问答中，DeepSeek 的表现不逊于 GPT-4
- Function Calling：DeepSeek 原生支持工具调用，无需额外适配
- 当前使用官方模型名 `deepseek-v4-flash`（旧别名 deepseek-chat 已于 2026-07-24 停用，过渡期指向 v4-flash 非思考模式）
- **智谱 GLM 免费版踩过的坑**：单并发 + 15:00-23:00 高峰限流，且高峰可能返回空 content 导致后端崩溃。故切换回 DeepSeek，智谱 key 保留为 fallback
- 一个踩过的坑：LLM 不总是主动调 `search_knowledge`，所以我在 `/query` 端点做了 **强制检索注入**——先把 query 查知识库，再把结果塞进 system prompt，确保每轮回答都有知识支撑，不依赖模型自己的"意愿"

### 为什么用 ChromaDB 而不是 Milvus / Qdrant？

**按实际规模选型，不盲目上分布式。**
- ChromaDB 是嵌入式向量数据库，零依赖，进程内运行
- 当前知识库 166 个 chunk，ChromaDB 完全够用，检索延迟 < 50ms
- 如果扩大到 100 万级，瓶颈会依次出现在：向量检索延迟（换 HNSW 参数可撑一撑）→ 单机内存（需换 Milvus/Qdrant）→ 多路召回的吞吐（需加缓存层）
- **迁移路径是明确的：** ChromaDB 的数据导出到 Milvus 只需要改 `collection.query()` 那几行，检索逻辑本身是框架无关的

### 为什么自己造多路召回的轮子，而不是直接上 LangChain？

**LangChain 是胶水，不是架构。**
- LangChain 的 `ensemble_retriever` 确实能快速拼出混合检索，但它的 RRF 实现是硬编码的，调不了 `k` 值和权重
- 我需要 `sparse_weight=2.0` 这个参数来平衡中英文检索——中文场景 BM25 的 term 匹配比向量更可靠（"动态计算图" 这个词，英文语义匹配就够了，中文必须 BM25 才能精确命中）
- 自己实现的好处：**调试路径是透明的**。出问题我知道去查 `retrieve()` → `rrf_merge()` → `rerank()` 哪一步
- **和 Reranker 的关系：** BM25 会拉入关键词噪声。原设计用 Cross-Encoder 二次精排压噪声，但 40 题评测（2026-08）连续两轮显示：中文小语料下 Reranker 无增益（0.27 ≈ 单路向量 0.27）。保留开关、默认关闭，避免无效延迟

### 为什么用滑动窗口限流，而不是令牌桶？

**选择标准是"谁先扛不住"。**
- 令牌桶（Token Bucket）：适合突发流量，积攒的令牌可以一次性消费。但 DeepSeek API 不允许突发调用，被限会返回 429
- 滑动窗口（Sliding Window）：严格保证每分钟不超过 N 次，对上游 API 更友好
- 实现上用了 `collections.deque` 存时间戳，O(1) 入队出队，不需要 Redis 或外部依赖
- 如果未来需要分布式限流（多个容器实例），会迁移到 Redis + Lua 脚本

### Multi-Agent 为什么是"研究员→写作者→审核员"三阶段？

**不是花哨，是解决单次 LLM 调用的三个结构性缺陷。**
- **研究员**：检索知识库 + 提取关键信息，专注精度，不参与生成
- **写作者**：根据研究员提供的材料组织文章，专注表达
- **审核员**：检查事实错误和逻辑漏洞，回退到写作者重新修改
- **为什么不用链式提示（Chain-of-Thought）：** CoT 在单个 prompt 里模拟多步推理，但 LLM 在长上下文中容易"中途掉线"——写到后面忘了前面的约束。Agent 之间的显式状态传递（研究员输出→写作者输入）避免了这个问题
- **状态驱动机**：写作者返回后检查状态，已审核通过就不重复跑，防止写作者 ↔ 审核员死循环

---

## API 接口

| 接口 | 鉴权 | 说明 |
|------|------|------|
| `GET /health` | 免鉴权 | 健康检查 |
| `POST /query` | X-API-Key | 标准 RAG 问答 |
| `POST /query/stream` | X-API-Key | 流式问答（SSE：tool / token / done 事件） |
| `POST /query/hybrid` | X-API-Key | 混合检索，可选 Reranker |
| `POST /doc` | X-API-Key | 添加知识 |
| `GET /kb/docs` | X-API-Key | 获取知识库全部文档 |
| `POST /doc/preview` | X-API-Key | 文档预览（`{filename, content: base64}` → 文本前 5000 字符） |
| `POST /agent/write` | X-API-Key | Multi-Agent 写作流水线 |

### 测试示例

```powershell
# 流式问答（PowerShell 用单引号包 JSON，\" 无效）
curl.exe -N -X POST http://localhost:8000/query/stream -H "Content-Type: application/json" -H "X-API-Key: rag-secret-key-2024" -d '{"question":"什么是RAG"}'

# 混合检索（稠密 + BM25 + Reranker）
curl.exe -X POST http://localhost:8000/query/hybrid -H "Content-Type: application/json" -H "X-API-Key: rag-secret-key-2024" -d '{"question":"What is PyTorch?","use_reranker":true}'

# Multi-Agent 写作
curl.exe -X POST http://localhost:8000/agent/write -H "Content-Type: application/json" -H "X-API-Key: rag-secret-key-2024" -d '{"topic":"PyTorch 动态计算图","max_retries":2}'
```

---

## 环境变量

在 `.env` 中配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 必填 |
| `ZHIPU_API_KEY` | 智谱 API Key（fallback） | 可选 |
| `LLM_BASE_URL` | 覆盖 LLM 端点 | 按 key 自动选 |
| `LLM_MODEL` | 覆盖模型名 | deepseek-v4-flash |
| `RAG_API_KEY` | API 鉴权密钥 | rag-secret-key-2024 |
| `RAG_RATE_LIMIT` | 每分钟最大请求数 | 30 |

---

## 检索评测

> 现行口径（2026-08-07 更新）：40 题评测集（`eval/eval_set.json`），生产与评测统一权重 = dense 1.0 + sparse 2.0（原评测 1.0/1.0 低估了真实能力，对比实测见 docs/OPS-NOTES.md 第 14 节）。

| 策略 | R@5 | R@10 | MRR | Hit@5 |
|------|:---:|:----:|:---:|:-----:|
| dense 单路向量 | 0.27 | 0.27 | 0.43 | 0.60 |
| **hybrid（dense + BM25×2 + RRF）** | **0.47** | **0.34** | **0.68** | **0.88** |
| hybrid + Reranker | 0.27 | 0.33 | 0.47 | 0.60 |

> **结论：** 混合检索显著优于单路向量（R@5 +0.20，Hit@5 +0.28）；偏关键词权重（sparse=2.0）优于均等权重；Reranker 在中文小语料无增益，连续两轮评测验证，默认关闭。

运行方法（检索层零 token）：

```powershell
python eval_rag.py --retrieval-only
```

---

以下为早期评测存档（`eval_retrieval.py`，28 篇文档 × 5 题小样本，已被 40 题评测集取代）：

| 方法 | Recall@5 平均 | Recall@10 平均 | 说明 |
|------|:------------:|:-------------:|------|
| 单路向量 | 0.56 | 0.56 | 仅依赖语义匹配 |
| 混合+RRF 融合 | 0.60 | 0.42 | BM25 引入噪声，RRF 未有效过滤 |
| 混合+Reranker | **0.56** | **0.58** | Cross-Encoder 压制噪声，Top-10 略有提升 |

运行方法：

```bash
# 确保 Docker 容器运行中
python eval_retrieval.py
```

> **结论：** 在小规模、高质量知识库中，单路向量和混合+Reranker 表现接近。混合+RRF 在 Top-10 上 Recall 较低，因为 BM25 拉入了不相关文档。Reranker 通过 Cross-Encoder 二次排序恢复了召回率。生产级系统采用多路召回+Reranker 的核心原因是在大规模、含噪声的语料中，同时覆盖语义与关键词的检索盲区。

## 运行测试

```powershell
python tests\test_api.py
```

需要 Docker 容器运行中。测试项包括：健康检查、RAG 查询、混合检索、Reranker、API 鉴权、知识库统计、限流。

## 运维

部署、镜像拉取、npm 构建、后端排障等全套踩坑经验见 [docs/OPS-NOTES.md](docs/OPS-NOTES.md)。

## 技术栈

`Python 3.11` `FastAPI` `ChromaDB` `Sentence-Transformers` `BM25` `Cross-Encoder` `React` `TypeScript` `Vite` `nginx` `Docker`

[→ GitHub](https://github.com/inervers/RAGNEXUS)
