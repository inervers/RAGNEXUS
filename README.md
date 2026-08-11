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
├── mcp_server.py        ← MCP thin wrapper（stdio / streamable HTTP）
├── mcp_client_test.py   ← clone-independent stdio lifecycle smoke
├── mcp_http_client_test.py ← streamable HTTP lifecycle smoke
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
├── requirements-api.txt ← 标准 API 镜像的 pinned 直接依赖
└── requirements-mcp.txt ← 可选 MCP server/client 的 pinned 依赖
```

---

## 快速开始

### 本地运行

```powershell
# 1. 复制 .env.example 为 .env，填写 DEEPSEEK_API_KEY 与随机 RAG_API_KEY
# 2. 启动 API 服务（默认 8000 端口）
python rag_api.py

# 3. 启动前端 dev server（另一个终端，默认 5173 端口）
cd frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`（vite dev 已配置代理转发到 8000）。
首次使用时在侧边栏输入与后端一致的 `RAG_API_KEY`；它只保存在当前标签页的 `sessionStorage`，不会写入前端 bundle 或 localStorage。

### Docker 部署

```powershell
# 先复制示例配置并填写真实 key
Copy-Item .env.example .env

# fresh clone 先构建包含 verified V2/V1 snapshots 的标准镜像
docker compose build rag-api

# 只对不存在/空的 candidate 执行一次；非空目标会 fail-fast
docker compose --profile tools run --rm kb-materialize

# 启动 API + 前端；已有 verified candidate 时直接执行这一行
docker compose up -d --build
```

启动后：
- 前端 → `http://localhost:8080`（nginx 托管，同源请求转发到 API）
- API 服务 → `http://localhost:8000`
- 前端 API 走同源（`API_BASE=""`），由 nginx 正则转发 `/health|/query|/doc|/kb|/agent`，无需跨域配置

默认镜像不依赖个人旧镜像、`.wheels`、本机模型目录或真实数据库。生产 Embedding 固定为 `paraphrase-multilingual-MiniLM-L12-v2@e8f8c211... + masked_mean`；镜像按 tracked manifest 下载并逐文件校验 size/SHA256，运行时只从本地 snapshot 加载。镜像同时保留经过 manifest 校验的 V1 MiniLM snapshot，供数据库与模型成对回滚。CPU Torch 从官方 CPU wheel index 安装，其余 Python 依赖默认使用阿里云镜像。

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
| **Multi-Agent 写作** | Researcher→Writer→Reviewer 有界协作流水线；未达阈值时 Reviewer issues 回灌下一轮 Writer，带 trace 与持久化记忆 |
| **知识库管理** | 支持 10 MiB 内 UTF-8 TXT/PDF；preview 最多展示 5000 字符，正式 import 从原始文件重新解析完整文本 |

前端为终端风格 4-tab 布局：问答 / 混合检索 / 知识库 / Agent 写作，支持暗色主题与 localStorage 会话持久化。

前端回归命令：

```powershell
cd frontend
npm test
npm run build:check
npm run build
```

`build:check` 会检查 App 与 fxbits 组件的完整 TypeScript 契约。服务离线时 Sidebar 与问答主区统一显示 offline；Reranker 缺少 Cross-Encoder 时结果区会显式标为 fallback。

### MCP 接入与验收

MCP 层只适配协议，检索、鉴权、限流和 trace 仍由 FastAPI 生产入口负责。工具成功响应返回机器可读的 `chunks/strategy/trace_id/stats`，失败响应返回稳定的 `error.code/message/trace_id`。

```powershell
python -m pip install -r requirements-mcp.txt

# stdio（Claude / Cursor / Codex 等本地客户端）
python mcp_server.py

# streamable HTTP
python mcp_server.py --transport http --port 8101
```

后端已启动时，可分别验证两种 transport：

```powershell
python mcp_client_test.py
python mcp_http_client_test.py --url http://127.0.0.1:8101/mcp
```

### 生产工程化

| 能力 | 实现 |
|------|------|
| API 鉴权 | X-API-Key 请求头校验，无 Key 返回 401 |
| 速率限制 | 滑动窗口限流（30次/分钟），超限返回 429 |
| 结构化日志 | 全链路 trace_id 追踪，JSON 格式写入文件 |
| Docker 部署 | 标准 Python 3.11 API 镜像 + nginx 前端；固定模型 revision；tmpfs smoke |
| SSE 流式 | 后端 X-Accel-Buffering: no + nginx proxy_buffering off；最终 done event 与非流式接口共享 `sources/retrieval_trace/trace_id` |
| MCP 交付 | stdio + streamable HTTP；结构化成功/错误 payload；客户端按脚本目录定位 server |

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

## 设计决策

### 生成服务与检索路径

- 当前生成层通过兼容接口接入 DeepSeek，模型和凭据由环境变量配置，业务代码不绑定固定供应商。
- 标准问答入口不依赖 LLM 自主决定是否检索。`/query` 与 `/query/stream` 先通过 `RetrievalService` 完成一次显式检索，再把同一批 `selected` chunks 注入生成上下文。
- 生成阶段移除 `search_knowledge` 工具，避免单次请求出现两套检索结果；供应商限流和网络故障记录在 `docs/OPS-NOTES.md`。

### 向量存储

- 当前语料规模使用嵌入式 ChromaDB，以较低部署复杂度提供向量检索和 metadata 管理。
- V1 archive 为 166 个 chunks；隔离式 V2 artifact 为 10 个逻辑文档、184 个 content-addressed chunks。两者属于不同语料版本。
- `RetrievalService` 将向量存储与生成层契约隔离。扩大规模后可根据延迟、内存、过滤、并发和运维需求评估 Milvus、Qdrant 等方案；迁移仍需完成数据重建、索引配置与回归评测。

### Hybrid Search 与可观测性

- 检索使用 dense + BM25 两路召回，并通过可配置权重的 RRF 融合排名。RAG-06 在 development split 比较 1:1、1:2、1:3 后选择 Dense:Sparse = 1:2，再冻结到 held-out 验证。
- 关键检索流程由项目代码实现，以暴露候选集、权重、排名和 trace，便于定位 `retrieve()`、RRF 融合或 Reranker 阶段的问题。
- Cross-Encoder 是可选精排层。标准可复现实验镜像缺少 verified snapshot 时显式标记 `fallback` 或 `not_evaluated`，不计为有效重排成绩。

### 限流

- 当前单实例使用基于 `deque` 的滑动窗口，严格限制固定时间窗口内的请求次数，并保持 O(1) 的过期时间戳清理和追加。
- 该实现适合当前单进程部署。多实例部署时需要迁移到 Redis 等共享状态存储，并通过原子操作保证全局限额一致。

### Multi-Agent 工作流

- Researcher 负责检索与材料整理，Writer 负责生成，Reviewer 输出结构化 `issues/rating/verdict`。
- 未通过时，Reviewer issues 会显式进入下一轮 Writer prompt，并写入 trace，避免质量反馈只停留在日志中。
- 工作流设置有界重试；只有满足通过条件时标记成功，重试耗尽则返回失败状态。对于不需要角色分工和反馈循环的简单请求，标准单次 RAG 路径仍是更低成本的选择。

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
| `POST /doc/preview` | X-API-Key | 文档预览（`{filename, content: base64}` → `preview/full_length/truncated`） |
| `POST /doc/import` | X-API-Key | 从原始 base64 重新解析并导入完整文档，不消费 preview 文本 |
| `POST /agent/write` | X-API-Key | 三角色有界协作流水线，`max_retries` 严格限制为 0–3 |

### 测试示例

```powershell
# 流式问答（PowerShell 用单引号包 JSON，\" 无效）
curl.exe -N -X POST http://localhost:8000/query/stream -H "Content-Type: application/json" -H "X-API-Key: $env:RAG_API_KEY" -d '{"question":"什么是RAG"}'

# 混合检索（稠密 + BM25 + Reranker）
curl.exe -X POST http://localhost:8000/query/hybrid -H "Content-Type: application/json" -H "X-API-Key: $env:RAG_API_KEY" -d '{"question":"What is PyTorch?","use_reranker":true}'

# Multi-Agent 写作
curl.exe -X POST http://localhost:8000/agent/write -H "Content-Type: application/json" -H "X-API-Key: $env:RAG_API_KEY" -d '{"topic":"PyTorch 动态计算图","max_retries":2}'
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
| `RAG_API_KEY` | API 鉴权密钥；缺失、旧默认值或模板占位符会拒绝启动 | 必填，无默认值 |
| `RAG_CORS_ORIGINS` | 浏览器精确 origin，逗号分隔，禁止 `*` | 本地 5173/8080 |
| `RAG_RATE_LIMIT` | 每分钟最大请求数 | 30 |
| `RAG_CHROMA_HOST_DIR` | Compose 挂载的宿主机 Chroma 目录 | `./chroma_db_v2_candidate` |
| `RAG_EMBEDDING_MODEL_SOURCE` | 镜像内或本地 verified snapshot 路径 | multilingual V2 snapshot |
| `RAG_EMBEDDING_MANIFEST` | 模型 ID/revision/pooling/files 的 tracked manifest | multilingual V2 manifest |

---

## 检索评测

RAG-02 已将检索指标改为基于 `relevant_chunk_ids` 的 Recall@5/10、MRR@10 和 HitRate@5，并把 API error、empty、unscored、Reranker fallback 分开记录。旧 40 题只有关键词标注，旧 README/OPS 中的 Recall、MRR、HitRate 只保留为历史记录，不是当前成绩。

RAG-04 已建立隔离的 V2 corpus：

- 10 个逻辑文档，184 个唯一 chunks；只允许 `public + current`。
- chunk ID：`doc_id#sha256(normalized_chunk_text)[:16]`。
- corpus SHA256：`175a3b5f11b4db312418ebfb73ee1c5439519dd7a191faffc3bcaad0076c6802`。
- `chroma_db_v2_candidate` 与 V1 `chroma_db`、来源待核验的 `chroma_db_v2` 独立；物化前必须停容器，禁止本地/容器并发访问同一 bind mount。

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
python materialize_kb_v2.py --artifact kb_v2/build --target chroma_db_v2_candidate --check-only

# 仅在目标不存在/为空、rag-api 已停止时物化
python materialize_kb_v2.py --artifact kb_v2/build --target chroma_db_v2_candidate --batch-size 32
```

上面的 Python 命令适合本机已经存在 `.rag06-models` snapshot 的开发环境。fresh clone 推荐使用 `docker compose --profile tools run --rm kb-materialize`：标准镜像内已经包含公开 V2 artifact、materializer 与经过 manifest 校验的模型，不需要本机另装 Python/Torch/Chroma。

生产 API、物化器与 RAG-06 实验共用同一个 verified embedding runtime。V2 collection metadata 同时记录 model ID、revision、pooling 与 snapshot aggregate SHA256；任一项与运行配置不一致时服务 fail-fast，禁止把不同向量空间静默混写。Compose 默认目标为 `chroma_db_v2_candidate`，旧 V1 库不覆盖、不删除。

2026-08-11 的生产迁移验收已完成：candidate 为 184 chunks，stored/corpus IDs 完全一致；production development 24 题与 heldout 16 题相对 RAG-06 frozen `hybrid-1-2` 逐题指标均为 0 mismatch。API health 返回 `chunks=184 + masked_mean`，前端与 Nginx proxy smoke 通过。原始 API 路径评测保存在 [`production-v2-development.json`](eval/experiments/production-v2-development.json) 与 [`production-v2-heldout.json`](eval/experiments/production-v2-heldout.json)。Reranker 仍是显式 fallback，不计作 Cross-Encoder 成绩。

回滚必须让数据库和 Embedding 成对切换，不能只换数据库路径：

```powershell
$env:RAG_CHROMA_HOST_DIR="./chroma_db"
$env:RAG_EMBEDDING_MODEL_SOURCE="/opt/models/legacy-minilm-l6-v2"
$env:RAG_EMBEDDING_MANIFEST="/opt/models/manifests/all-MiniLM-L6-v2.json"
$env:RAG_EMBEDDING_MODEL_ID="sentence-transformers/all-MiniLM-L6-v2"
$env:RAG_EMBEDDING_MODEL_REVISION="1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
$env:RAG_EMBEDDING_POOLING="legacy_mean"
docker compose up -d
```

恢复 V2 时移除这 6 个当前终端环境变量，再执行 `docker compose up -d`。

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
