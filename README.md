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
├── Dockerfile           ← 标准可复现后端构建（CPU Torch + 固定 MiniLM revision）
├── Dockerfile.legacy    ← 本机旧镜像 + 离线 wheels 的历史 fallback，非默认
├── docker-compose.yml   ← 真实数据部署（会挂载 ./chroma_db）
├── docker-compose.smoke.yml ← tmpfs fixture 隔离验收，不读取真实数据库/.env
└── requirements-api.txt ← 标准 API 镜像的 pinned 直接依赖
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
# 先复制示例配置并填写真实 key
Copy-Item .env.example .env

# 默认标准构建：Python 3.11 + CPU Torch + 固定 MiniLM snapshot
docker compose up -d --build
```

启动后：
- 前端 → `http://localhost:8080`（nginx 托管，同源请求转发到 API）
- API 服务 → `http://localhost:8000`
- 前端 API 走同源（`API_BASE=""`），由 nginx 正则转发 `/health|/query|/doc|/kb|/agent`，无需跨域配置

默认镜像不依赖个人旧镜像、`.wheels`、本机模型目录或真实数据库。MiniLM revision 固定为 `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`，6 个必需文件在 build 阶段逐一校验 SHA256，运行时仍为 `local_files_only`。CPU Torch 从官方 CPU wheel index 安装，其余 Python 依赖默认使用阿里云镜像；均可通过 build args 覆盖。

提交或部署前可先运行完全隔离的 smoke：

```powershell
.\scripts\smoke-docker.ps1
```

该脚本使用 18000/18080 端口和 tmpfs fixture，验证 API health、无 key 401、Hybrid 检索、前端首页与 Nginx 代理，最后自动销毁容器/临时数据。它不读取 `.env`、`chroma_db` 或 `chroma_db_v2`，也不调用外部 LLM。

`Dockerfile.legacy` 只保留 2026-08-02 国内网络故障时的增量构建证据；需要本机 `ragnxus-rag-api:0.5.17-backup` 与 `.wheels`，不得作为 fresh clone 默认路径。更多历史细节见 [docs/OPS-NOTES.md](docs/OPS-NOTES.md)。

### Agent 记忆持久化

Agent 的写作记忆保存在本地 `memory/` 目录，容器重建后记忆不丢失。

---

## 功能模块

| 功能 | 说明 |
|------|------|
| **标准 RAG 问答** | Function Calling 驱动，自动检索知识库 + LLM 回答，SSE 流式 + 打字动画 + 取消 |
| **混合检索** | 稠密向量 + BM25 + RRF；V2 评测冻结 Dense:Sparse=1:2，目标 Embedding 为 multilingual MiniLM |
| **Reranker 精排** | 可选 Cross-Encoder；模型缺失会显式 fallback，RAG-06 未把 fallback 计作有效成绩 |
| **Multi-Agent 写作** | 研究员→写作者→审核员协作流水线，带持久化记忆与评分/重试循环 |
| **知识库管理** | 支持 .txt/.pdf 拖拽上传，PDF 实时预览（/doc/preview），分页浏览与跳页 |

前端为终端风格 4-tab 布局：问答 / 混合检索 / 知识库 / Agent 写作，支持暗色主题与 localStorage 会话持久化。

### 生产工程化

| 能力 | 实现 |
|------|------|
| API 鉴权 | X-API-Key 请求头校验，无 Key 返回 401 |
| 速率限制 | 滑动窗口限流（30次/分钟），超限返回 429 |
| 结构化日志 | 全链路 trace_id 追踪，JSON 格式写入文件 |
| Docker 部署 | 标准 Python 3.11 API 镜像 + nginx 前端；固定模型 revision；tmpfs smoke |
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
- 一个踩过的坑：LLM 不总是主动调 `search_knowledge`。现在 `/query` 与 `/query/stream` 都先通过统一 `RetrievalService` 显式检索，再把同一批 `selected` chunks 注入生成上下文；生成阶段移除检索工具，避免一次请求出现两套检索结果

### 为什么用 ChromaDB 而不是 Milvus / Qdrant？

**按实际规模选型，不盲目上分布式。**
- ChromaDB 是嵌入式向量数据库，零依赖，进程内运行
- V1 archive 为 166 个 chunk；隔离式 V2 artifact 当前为 10 个逻辑文档、184 个 content-addressed chunks。两个数字来自不同语料版本，不能直接比较质量
- 如果扩大到 100 万级，瓶颈会依次出现在：向量检索延迟（换 HNSW 参数可撑一撑）→ 单机内存（需换 Milvus/Qdrant）→ 多路召回的吞吐（需加缓存层）
- **迁移路径是明确的：** ChromaDB 的数据导出到 Milvus 只需要改 `collection.query()` 那几行，检索逻辑本身是框架无关的

### 为什么自己造多路召回的轮子，而不是直接上 LangChain？

**LangChain 是胶水，不是架构。**
- LangChain 的 `ensemble_retriever` 确实能快速拼出混合检索，但它的 RRF 实现是硬编码的，调不了 `k` 值和权重
- 当前所有入口统一使用 `dense_weight=1.0 / sparse_weight=2.0`；RAG-06 development 在 1:1、1:2、1:3 中选择 1:2，冻结后 heldout 复验
- 自己实现的好处：**调试路径是透明的**。出问题我知道去查 `retrieve()` → `rrf_merge()` → `rerank()` 哪一步
- **和 Reranker 的关系：** BM25 可能拉入关键词噪声，Cross-Encoder 可做候选精排；标准可复现镜像当前没有 verified Cross-Encoder snapshot，RAG-06 明确记为 `not_evaluated`，不再沿用旧评测的“无增益”结论

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

RAG-02 已将检索指标改为基于 `relevant_chunk_ids` 的 Recall@5/10、MRR@10 和 HitRate@5，并把 API error、empty、unscored、Reranker fallback 分开记录。旧 40 题只有关键词标注，旧 README/OPS 中的 Recall、MRR、HitRate 只保留为历史记录，不是当前成绩。

RAG-04 已建立隔离的 V2 corpus：

- 10 个逻辑文档，184 个唯一 chunks；只允许 `public + current`。
- chunk ID：`doc_id#sha256(normalized_chunk_text)[:16]`。
- corpus SHA256：`175a3b5f11b4db312418ebfb73ee1c5439519dd7a191faffc3bcaad0076c6802`。
- `chroma_db_v2` 与 V1 `chroma_db` 独立；物化前必须停容器，禁止本地/容器并发访问同一 bind mount。

RAG-05 已冻结绑定 V2 manifest 的新版 40 题：`exact` 10、`semantic` 8、`troubleshooting` 8、`multidoc` 6、`version_conflict` 4、`unanswerable` 4。其中 development 24 题用于配置迭代，heldout 16 题只在配置冻结后运行。所有正样本都绑定真实 doc/chunk ID 和 `doc_id@commit`；无答案题不伪造 relevant IDs。

```powershell
# 默认只运行 development 24 题
python eval_rag.py --retrieval-only

# 配置冻结后才显式解锁 heldout 16 题
python eval_rag.py --retrieval-only --split heldout --allow-heldout
```

`eval/eval_set.schema.json` 固化字段契约，`eval_dataset.py` 还会严格验证题数、分类/split 分布、manifest SHA256、chunk 归属和来源提交。未带 `--allow-heldout` 请求 heldout/all 会在发送 HTTP 前失败。

RAG-06 只用 development 选择并冻结 `paraphrase-multilingual-MiniLM-L12-v2 + Hybrid 1:2 + top_k=10`，随后一次性运行 heldout。16 道 heldout 中 14 道正样本的结果为：Recall@5 0.8929、Recall@10 0.9286、MRR@10 0.7917、HitRate@5 1.0000；另 2 道无答案题不混入正样本检索指标。原始结果、freeze 和 Case 分析见 `eval/experiments/`。

这些数字只代表当前 184-chunk 项目知识域回归集，不代表开放域泛化或生产 SLA。检索 median 16.507 ms、P95 20.857 ms 来自同一容器单进程相对实验，也不能当成并发性能结论。heldout 的 multidoc Recall@5 只有 0.5，下一步应优先做 source diversity/query decomposition，而不是继续微调 RRF 权重。

```powershell
# 生成确定性的 JSONL + manifest，不访问 Chroma
python build_kb_v2.py --catalog kb_v2/catalog.json --output kb_v2/build

# 只验证 artifact 与目标路径安全性
python materialize_kb_v2.py --artifact kb_v2/build --target chroma_db_v2 --check-only

# 仅在目标不存在/为空、rag-api 已停止时物化
python materialize_kb_v2.py --artifact kb_v2/build --target chroma_db_v2 --batch-size 1
```

V2 的目标 Embedding 已根据评测选为 multilingual MiniLM，但默认 `rag_api.py` 与真实持久库尚未直接切换：现有 document embeddings 来自旧 model/pooling，只换 query encoder 会造成向量口径不一致。生产迁移必须在新数据库中全量重算 184 chunks、校验后再显式切换，并保留旧库回滚。

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
