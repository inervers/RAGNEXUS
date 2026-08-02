# RAGNEXUS 运维笔记

> 2026-07-31 实战沉淀：Docker 前端部署 + 后端排障 + LLM 切换的全套经验。
> 下次遇到同类问题，按这份手册走，不要重新踩坑。

---

## 1. 部署基本盘

| 服务 | 端口 | 说明 |
|---|---|---|
| rag-api | 8000 | FastAPI 后端（bind mount 挂载 rag_api.py / rag_multiagent.py，改代码 `restart` 即生效） |
| rag-frontend | 8080 | nginx 静态站点（前端改代码必须 **重新 build** 镜像，restart 不够） |

**项目命名（2026-08-02 统一）**：本地文件夹/仓库 RAGNEXUS；docker compose 顶层 `name: ragnxus` 固定项目名（默认项目名=文件夹名，镜像/volume 会带前缀）。容器 `ragnxus-api` / `ragnxus-frontend`，镜像 `ragnxus-rag-api` / `ragnxus-rag-frontend`。

**知识库数据挂载（2026-08-02 起）**：`./chroma_db:/data/chroma_db`（**bind mount**），与本地 `python rag_api.py` 共享同一份数据。**别再改回 named volume**——双数据源是"知识库消失"事故的根源（见 11.3 节）。

```powershell
cd RAGNEXUS        # 项目根目录（Docker 命令都在这里执行）

docker compose ps                          # 容器状态（Up 才是活着）
docker compose up -d rag-frontend          # 创建并启动（注意：build ≠ up，只 build 不会起容器！）
docker compose logs rag-api --tail=50      # 后端日志
docker compose restart rag-api             # 后端改动生效（bind mount 不需要 rebuild）
docker compose build rag-frontend          # 前端改动后重建镜像
docker compose up -d rag-frontend          # 重建后重新启动
```

**最容易犯的错**：只 `build` 不 `up`，浏览器打不开 8080——`docker ps -a` 里根本没有容器。

---

## 2. Docker 镜像拉取（国内网络）

**2026 年现状**：国内免费镜像加速器基本全军覆没：

| 加速器 | 结果 |
|---|---|
| 阿里云个人加速器 | 403（服务实质关闭） |
| DaoCloud docker.m.daocloud.io | DNS 解析失败 |
| 轩辕 docker.xuanyuan.me | 429 限流 |
| 上海交大 | 2026-06 被监管下架 |

**唯一可靠解法：开 Verge（Clash 代理）后直连 Docker Hub。**

关键坑：

1. **BuildKit 的 `FROM` 拉取不继承 `docker pull` 的代理路径**。正确姿势：
   ```powershell
   # 开代理后手动拉基础镜像进本地缓存
   docker pull node:20-alpine
   docker pull nginx:alpine
   # 之后构建全程离线（FROM 命中缓存，不再碰网络）
   docker compose build rag-frontend
   ```
2. Docker Desktop 改代理后要**重启**才生效。
3. 基础镜像缓存：node:20-alpine、nginx:alpine 已拉好，构建 metadata 秒过。

---

## 3. npm ci 崩溃坑（前端 Dockerfile）

**症状**：`npm ci` 跑 72 秒后崩溃，报 "Exit handler never called!"，**退出码是 0**——导致 `cmd1 || cmd2` 兜底逻辑完全不触发。

**根因**：容器内走代理链路导致 npm 挂起；退出码 0 是 npm 的 bug 行为。

**已落地的解法**（frontend/Dockerfile）：
```dockerfile
RUN npm config set registry https://registry.npmmirror.com \
    && ( (npm ci --no-audit --no-fund && test -x node_modules/.bin/tsc) || npm install --no-audit --no-fund )
```

要点：
- **容器内不用代理**，固定 npmmirror 直连（代理是 72 秒挂起的根源）
- `test -x node_modules/.bin/tsc` 做**真实成功校验**（退出码 0 不可信）
- 失败后 `npm install` 兜底补装
- npm ci 崩溃还会导致 rolldown（vite 8）原生绑定 `@rolldown/binding-linux-x64-musl` 缺失报错，本质同源

`.dockerignore` 已排除 node_modules/dist/.git（构建上下文 109MB → 1.5kB，防止 Windows 版依赖污染容器）。

---

## 4. LLM 配置（DeepSeek 优先）

```ini
# .env（不进 git）
DEEPSEEK_API_KEY=sk-xxx          # 主用
ZHIPU_API_KEY=xxx                # fallback，备用
RAG_API_KEY=rag-secret-key-2024
```

代码逻辑（rag_api.py）：
```python
LLM_API_KEY = DEEPSEEK_API_KEY or ZHIPU_API_KEY
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com" if DEEPSEEK_API_KEY else "https://open.bigmodel.cn/api/paas/v4")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash" if DEEPSEEK_API_KEY else "glm-4.7-flash")
```

**模型版本事实（2026-08）**：
- 官方现行模型名：`deepseek-v4-flash`（284B 参数 / 13B 激活 / 1M 上下文）和 `deepseek-v4-pro`
- 旧别名 `deepseek-chat` / `deepseek-reasoner` 已于 **2026-07-24 官方停用**（过渡期指向 v4-flash 的非思考/思考模式）；别名失效后换 `deepseek-v4-flash`
- 切模型只改 `.env` 的 `LLM_MODEL` 即可，代码默认值在 rag_api.py / rag_multiagent.py

**智谱免费版（已弃用）的教训**：单并发 + 15:00-23:00 高峰限流，且**高峰可能返回空 content**（导致后端 NoneType 崩溃，见下节）。DeepSeek 无限流，这是切换的根本原因。

---

## 5. 后端故障速查

### 5.1 agent/write 500：LLM 返回空 content
**症状**：写作 tab 有评分没文章，curl 直连返回 `{"error":"Internal server error"}`。
**根因**：`_call_llm` 返回 `None`（模型空回复）→ `article[:500]` 抛 `TypeError: 'NoneType' object is not subscriptable`。
**已修**（rag_multiagent.py）：`article = self._call_llm(...) or ""`，`(research or "")[:200]`；max_tokens 1024→2048；`article[:500]`→`article[:5000]`（避免截断破坏 JSON）。
**前端兜底**（App.tsx）：article 为空显示"本次未生成文章内容，请重试"，不再静默空白。

### 5.2 /query/stream SSE 打字动画
- 后端：`StreamingResponse(media_type="text/event-stream")` + `X-Accel-Buffering: no`
- nginx：正则 location `~ ^/(health|query|doc|kb|agent)(/|$)` 转发 8000 + **`proxy_buffering off`**（不关则打字动画变一次性输出）
- SSE 事件格式：`{type:"tool"|"token"|"done"}`，前端按 `evt.type === "token"` 喂打字机

### 5.3 端点全集
| 端点 | 说明 |
|---|---|
| GET /health | 存活检查，返回 chunks 数 |
| POST /query/stream | SSE 流式问答 |
| POST /query | 非流式问答 |
| POST /query/hybrid | 混合检索（dense+sparse） |
| POST /doc | 上传文档 |
| GET /kb/docs | 知识库列表 |
| POST /doc/preview | `{filename, content: base64}` → `{title, content[:5000], full_length}` |
| POST /agent/write | 多 Agent 写作 `{topic, max_retries}` |

---

## 6. 前端

- `API_BASE=""`（同源）：本地 dev 靠 vite.config.ts proxy（`/health|/query|/doc|/kb|/agent` → 8000）；Docker 靠 nginx 正则转发
- **改了前端代码，浏览器必须 Ctrl+Shift+R 强刷**——旧缓存会导致"问问题不回答"这类假故障
- 4-tab 结构：问答 / 混合检索 / 知识库 / Agent 写作；问答打字动画 + 取消按钮（abortRef）；知识库 PAGE_SIZE=30 + 拖拽 PDF 预览（/doc/preview）

---

## 7. PowerShell 排障工具

```powershell
# curl.exe 才是真 curl（PowerShell 的 curl 是 Invoke-WebRequest 别名）
curl.exe -s http://localhost:8000/health

# JSON body 用单引号！\" 在 PowerShell 不是转义符 → 会 422
curl.exe -N -X POST http://localhost:8000/query/stream -H "Content-Type: application/json" -H "X-API-Key: rag-secret-key-2024" -d '{"question":"什么是RAG"}'

# 直连 8000 绕过 nginx：判断问题在前端还是后端
# 直连 OK + 浏览器不行 → 看 nginx / 前端缓存
# 直连失败 → 看后端日志
```

---

## 8. 安全纪律（血泪教训）

1. **改动先 commit + push，再动其他东西**。filter-repo 重写历史曾把整个前端最终版冲掉，靠会话记录逐条重放才找回来
2. `.env` / `replacements.txt` 在 .gitignore，**绝不 stage**；GITHUB_TOKEN 已删
3. pre-commit 钩子自动扫描密钥/合并冲突/行尾
4. 凭据轮换过：ZHIPU / DEEPSEEK / RAG / 百度 OCR 都是新 key
5. 推送后到 GitHub 页面确认文件内容（commit 信息 ≠ 实际内容，曾出现 commit 只含 2 个文件、其余在更早 commit 的情况）
6. **commit 元数据也暴露信息**：git 作者邮箱会随每个 commit 公开。做法：GitHub → Settings → Emails 开启 "Keep my email addresses private" + "Block command line pushes that expose my email"，再把本地 `git config user.email` 改成 noreply 地址（格式 `你的ID+用户名@users.noreply.github.com`）

---

## 9. 快速排障流程

```
浏览器打不开 8080
  → docker compose ps（容器在不在？不在就 up -d）
  → docker compose logs rag-frontend（nginx 报错？）

问答不回答
  → curl 直连 8000 /query/stream（后端通不通？）
  → 通 → 浏览器 Ctrl+Shift+R 强刷（前端缓存）
  → 不通 → docker compose logs rag-api（429 / timeout / Traceback？）

写作有评分没文章
  → curl 直连 /agent/write 看 article 字段（空串？500？）
  → 500 → 看日志 Traceback（多为 LLM 空 content）
  → 空串 → 模型高峰期质量问题，重试

改代码不生效
  → 后端：docker compose restart rag-api（bind mount）
  → 前端：docker compose build rag-frontend && up -d（镜像内是构建产物，restart 无效）
```

---

## 10. 历史排障记录（2026-07 沉淀）

> 更早会话积累的经验，按话题归档，遇到同类问题直接对号入座。

### 10.1 filter-repo 事故与恢复方法论（最痛教训）

**事故**：`git filter-repo` 重写历史时，把已提交的前端最终版（4-tab 终端 UI）和智谱迁移改动全部冲掉。症状是容器里跑的还是旧版代码（问答 500 错误，排查才发现是旧版 DeepSeek 硬编码）。

**恢复方法（已实战验证）**：
- 会话记录（JSONL）里的 toolUse / edit 消息是重建文件的**权威来源**，逐条重放 edit diff 可完整重建
- 重建后用 filter-repo 前的 grep 快照做**逐行对照验证**（关键行号吻合才算成功），再跑 tsc / vite build 确认无语法错误
- 重要文件的最后状态建议平时就留 grep 快照，恢复时对照用

**教训**：
- 改动先 commit + push，再动其他东西
- filter-repo / rebase / force push 这类大操作前，先 clone 一份完整备份
- 恢复工作的验证标准：不是“看起来对”，而是“与事故前快照逐行一致”

### 10.2 智谱 429 限流处理（切 DeepSeek 前的阶段）

**症状链**：问答 500 错误 → 排查发现容器内是旧版 DeepSeek 硬编码（filter-repo 冲掉了智谱迁移）→ 重新应用智谱改动后，错误变成智谱 429 Too Many Requests。

**原因**：智谱免费版模型（glm-4.7-flash）单并发 + 15:00-23:00 高峰限流。

**当时解法**：
- 超时调大到 120 秒（connect 10s）
- `_llm_post` 加 4 次重试（httpx.HTTPStatusError / 超时都重试）

**最终方案**：切换 DeepSeek（见第 4 节），免费限流模型不适合做生产依赖。

### 10.3 知识库重复内容清理

**症状**：知识库文档重复、检索结果冗余。

**处理链**：`audit_kb.py` 审计 → `cleanup_kb.py` 清理 → `kb_audit_report.md/json` 出报告 → 最后**把去重逻辑前移到导入入口**（上传时就查重，不再事后清理）。

**教训**：数据质量是入口问题——越早拦截，成本越低。事后清理永远追不上脏数据产生的速度。

### 10.4 前端 TypeScript 死代码策略（Vite 项目通用）

**症状**：旧版/重构后的死代码产生大量 TS 错误（未使用变量 TS6133、多余属性 TS2353）。

**决策**：逐一修补性价比低——修掉核心错误（约 6 个）后**跳过 tsc，直接 vite build**（vite 构建不强制类型检查，能产出产物即可）。

**注意**：RAGNEXUS frontend 的 Dockerfile 里 `npm run build` 包含 `tsc -b`，若以后重构引入死代码类型错误导致构建卡住，可参考此策略（改 build 脚本去掉 tsc 或修核心错误放行）。

**已落地（2026-08-02）**：`package.json` 的 `build` 已改为 `vite build`（跳过 tsc），新增 `build:check: tsc -b` 保留类型检查。Dockerfile 构建不再被 tsc 卡住（详见 11.5）。

### 10.5 凭据轮换记录

已做过一轮完整凭据轮换：ZHIPU / DEEPSEEK / RAG_API_KEY / 百度 OCR 全部换新。
- GITHUB_TOKEN 已删除，git remote URL 已去 token
- `.secrets.baseline`（detect-secrets）+ pre-commit 扫描作为防线
- `.env` / `replacements.txt` 在 .gitignore（已确认）

### 10.6 主题系统经验（前端通用）

CSS 变量只能改颜色——**要独特的设计语言（噪点纹理、像素硬阴影、粒子系统），必须在元素级做 DOM 选择器覆盖**，不能指望换 CSS 变量值搞定。paper / retro / nord 三套主题都是这个思路实现的。

---

## 11. 知识库"消失"事件与架构重构（2026-08-02）

> 今晚最大的教训：**"数据没了"多半是"数据换地方躺了"**。RAG 数据可能存在于多个位置（本地目录、docker volume、备份），先枚举再下结论。

### 11.1 718 块数据"清零"真相：存储位置切换

**症状**：知识库从 718 块变 7 块，怀疑数据丢失。
**真相**：数据没丢。7/27 前用 docker 部署（数据在 named volume `rag-agent-api_chroma_data`，718 块完好）；切到本地 `python rag_api.py` 后，后端读本地 `./chroma_db`（全新空库，只有内置示例）——"清零"其实是**后端数据路径变了**，不是数据被删。

**排查**：`docker volume ls` 确认 volume 存在 → 用本地 python 镜像挂载查内容（避免拉 alpine 被代理卡住）：
```powershell
docker run --rm -v rag-agent-api_chroma_data:/data rag-agent-api-rag-api python -c "import sqlite3;print(sqlite3.connect('/data/chroma.sqlite3').execute('select count(*) from embeddings').fetchone())"
```
**恢复**（整体拷贝，含 HNSW 索引）：
```powershell
docker run --rm -v <volume>:/data -v <项目绝对路径>:/work <镜像> sh -c "cp -a /data/. /work/chroma_db/"
```

### 11.2 知识库清理（cleanup_chroma.py）

docker volume 里 718 块含大量垃圾：`torch.Tensor` 坏块 266（导入 bug，source 写成 embedding 类型名）+ license 38 + LangChain 英文测试语料 ~120。清理后剩 **222 块**（自己的笔记 + 技术教程 + 项目文档）。

**ChromaDB 两个坑**：
- `collection.delete(where={"source": ...})` 返回值不可靠（打印出来是 1，实际删对了）——**以 count 前后差值为准**
- ChromaDB 0.5+ 的 metadata 在独立 `embedding_metadata` 表（不是 embeddings 表的 metadata 列），跨版本查库要先看 `sqlite_master` 的表结构

### 11.3 双数据源根治：bind mount

**根因**：named volume（`chroma_data:/data/chroma_db`）的数据在 docker 自己的存储区，与本地目录是**两套数据**。本地跑和容器跑各读各的 → 必然出现"一个 222 块、一个 7 块"的割裂。
**修复**：compose 改为 `./chroma_db:/data/chroma_db`（bind mount），本地和容器共享同一份数据，此类事故从机制上消除。

### 11.4 项目改名与 docker 命名

- 本地文件夹 `rag-agent-api` → `RAGNEXUS`（改名前先停后端 + `docker compose down`，Windows 上进程占用会拒绝改名）
- compose 顶层加 `name: ragnxus` 固定项目名（默认项目名=文件夹名，改名后镜像/volume 前缀会变）
- 改名重建遇到**容器名冲突**：旧容器（container_name 显式指定）停止状态仍占名，`docker ps -a` 看不到运行中的但容器在 → `docker rm <旧容器>` 后重建

### 11.5 前端构建 tsc 坑（已落地）

fxbits 组件缺 props 类型标注，`tsc -b && vite build` 在 docker 构建里卡死（几十个 TS 错误）。修复：`package.json` 的 `build` 改为 `vite build`（vite/esbuild 转译不查类型），`build:check` 保留。**本地 vite build 能过 ≠ docker 能过**——Dockerfile 的 `npm run build` 会真的跑 tsc。

### 11.6 docker 清理记录（2026-08-02）

已清：旧镜像 `rag-agent-api-*`、旧 volume（`rag-agent-api_chroma_data`、`ragnxus_chroma_data`）、rag_api 残留容器（hungry_satoshi / agitated_jepsen）、旧 HF 缓存 `rag-agent-api_hf_cache`。
**保留勿删**：`ragnxus_hf_cache`（模型缓存，删了要重新下载几 GB）、`spider-nexus_*`（其他项目数据）、匿名卷 41877a58（spider-nexus 的 Mongo 数据）。

## 12. 容器 LLM 调用 SSL EOF 排障（2026-08-02）

### 12.1 症状

- 浏览器问答：assistant 消息一直为空（打字动画空转），按钮恢复"发送"
- `/query/stream` 返回 200 但响应体 0 字节（流式生成器在第一个 yield 前抛异常，头已发出）
- `/query` 非流式返回 500 + trace_id
- 日志关键错误：`[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol`（0.6s 内失败，**连接层被掐**，不是超时也不是 429）

### 12.2 排查路径（结论：容器出口 TLS 全灭，本地正常）

1. 直连 8000 `/query/stream` → 200 空体 → 问题在后端 LLM 调用，不是前端解析
2. 日志定位 SSL EOF → 连接层问题（排除 key 无效、限流、模型名错误）
3. 宿主机 `curl api.deepseek.com/models` → **200**（key 有效，宿主网络可达）
4. 容器内 httpx → SSL EOF；容器 DNS 把 `api.deepseek.com` 解析到**日本 SoftBank 段** 171.105.220.186（海外节点）
5. compose 加 `dns: 223.5.5.5` → 解析恢复国内节点 43.242.198.77/14.29.51.120，但 TLS 仍被掐（14.29 立即 EOF，43.242 握手超时黑洞）
6. **结论**：WSL2 虚拟网卡出口到 DeepSeek 所有 CDN 节点的 TLS 全部被拦截，Windows 本机流量正常（DIRECT 200）
7. 开 Verge **TUN 模式** → 容器直连（proxy=None）**200**！TUN 透明接管 WSL2 出网，容器流量自动走代理

### 12.3 根因与解法

- **根因**：TUN 虚拟网卡路由接管了 WSL2 出网流量（Verge/v2rayN 类工具常见）；不开代理时容器直连 DeepSeek 的 TLS 被系统性拦截（EOF/超时），Windows 本机流量不受影响
- **解法**：容器需要 LLM 功能时开代理（TUN 模式即可，compose 无需任何代理配置）；本地 `python rag_api.py` 完全不受影响（直连正常）
- compose 已回退干净（不加 dns/extra_hosts/代理变量，TUN 透明接管最省事；extra_hosts 锁死 CDN 节点反而可能引入黑洞）

> **2026-08-02 补：此问题为校园网环境特性**。同一 compose（零配置）在家庭宽带上容器直连 `api.deepseek.com` 直接 200（DNS 解析到 43.242.198.77 香港节点直连通），本地与容器均无需代理。**换网络环境后先重测再排查，校园网结论不要外推到其他网络。**

### 12.4 本地跑的两个坑（同日发现）

1. **环境变量代理污染**：httpx `trust_env=True` 默认读 `HTTP(S)_PROXY` 环境变量，残留代理变量会让本地 httpx 走死代理 → 同样的 SSL EOF。修复：rag_api.py 两处 httpx client 加 `trust_env=False`（同步 + 异步各一处）
2. **ChromaDB 版本不兼容**：本地 pip 装的是 chromadb **1.5.9**，容器固定 **0.5.17**（requirements-base.txt），1.5.9 读 0.5.17 写的库报 `Error in compaction: mismatched types; Rust type u64 (as SQL type INTEGER) is not compatible with SQL type BLOB`（metadata 独立表 schema 不兼容，数据没坏）。本地跑要么 venv 装 0.5.17 对齐，要么 `RAG_CHROMA_DIR` 指向独立目录；**同库串行使用、版本必须一致**

### 12.5 快速验证清单

```powershell
# 容器内验证（需 Verge TUN 开启）：
docker exec ragnxus-api python -c "import httpx; r=httpx.get('https://api.deepseek.com/models', headers={'Authorization':'Bearer <key>'}, timeout=15, proxy=None); print(r.status_code)"
# 本地验证（不依赖代理）：
python -c "import httpx; r=httpx.get('https://api.deepseek.com/models', headers={'Authorization':'Bearer <key>'}, timeout=15, proxy=None); print(r.status_code)"
```

## 13. ChromaDB 0.5.17 → 1.5.9 升级（2026-08-02 完成）

### 13.1 背景与代码改动

容器固定 chromadb 0.5.17，本地 Python 3.13 是 1.5.9，双环境版本割裂（12.4 节）。决策：**容器升级到 1.5.9 统一**（本地降级 0.5.17 在 py3.13 上有兼容问题）。

代码改动：
- `requirements-base.txt`：chromadb 0.5.17 → 1.5.9
- `rag_api.py` MiniLMEmbedding 适配 1.x：新增 `__init__`、`name()` 返回 `"MiniLM-L6-v2-mean-pooling"`、`__call__(input)` 兼容 query 输入带 `.text` 的 Document 对象
- `migrate_chroma.py`：export/import 双模式，embedding 与 rag_api.py 完全一致（重算而非搬旧向量，避免 schema 转换风险），import 前先清空新库（init 块 id `doc_1..` 冲突）
- 兼容面：rag_advanced.py 只用 `collection.query/get`（1.x 兼容）；rag_multiagent.py 不碰 chromadb

### 13.2 构建网络地狱（pip 下载全灭矩阵）

家宽下为 build 下载 wheel 时，所有路径都试过一遍：

| 路径 | 结果 |
|---|---|
| pypi.org 直连（容器） | 10.6 kB/s 限速，ReadTimeout |
| 清华源 | **403 风控**（家宽出口 IP 26.x CGNAT 被拉黑，本地 pip 也中招） |
| 阿里云（容器） | 超时 |
| 腾讯云（容器 urllib） | 200，但 pip 大包下载 ReadTimeout |
| pypi.org + 代理（容器/本地） | `SSL: UNEXPECTED_EOF`（Clash 规则把 pypi 配了直连，直连出口对 pypi TLS 全灭，与 12 节同源） |
| **本地直连阿里云** | **可用**（chromadb 23.5MB 下完，35kB/s 慢但成） |
| 代理 + 官方源（本地） | 可用但节点不稳（IncompleteRead 断流，重跑续传） |

**踩坑补充**：
1. **清华源 403 是出口 IP 风控**，不是临时故障；pip config 里 `global.index-url` 指清华源的机器，本地装包要显式 `-i` 阿里云/腾讯云或走代理
2. **pip download 默认只为当前 Python 下载 wheel**：本地 py3.13 解析 `torch==2.5.1` 报 `versions: none`，因为 torch 2.5.1 没有 cp313 wheel（2.6.0 才支持 py3.13）。**不是源没有这个版本**，curl JSON API 查询 200 但 pip 就是找不到
3. **交叉下载指定目标平台**：`pip download <pkg> --only-binary=:all: --python-version 311 --implementation cp --abi cp311 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux1_x86_64 -i <源> [--proxy http://127.0.0.1:7897]`

### 13.3 增量镜像构建（关键方案）

**不要重装 torch**（900MB wheel + 2.5GB nvidia CUDA 依赖）。旧镜像 `ragnxus-rag-api`（0.5.17 时代）里 torch 2.5.1 全套已装好，直接拿它做基础镜像：

```dockerfile
FROM ragnxus-rag-api:0.5.17-backup   # 先 docker tag 旧镜像备份
COPY .wheels /wheels                 # 本地交叉下载的 chromadb 依赖树 wheel（~200MB）
RUN pip install --no-index --find-links=/wheels chromadb==1.5.9 && rm -rf /wheels
COPY rag_api.py rag_advanced.py rag_multiagent.py pdf_parser.py ocr_client.py .
```

- build 5 秒完成（旧镜像缓存全命中），绕开全部网络问题
- **build 前必须 `docker tag ragnxus-rag-api:latest ragnxus-rag-api:0.5.17-backup`**，否则新 build 覆盖旧镜像后无法回滚
- pip 离线装时已满足的依赖（torch/pydantic 等）不会被碰，只升级 chromadb 及新依赖

### 13.4 数据迁移（已执行）

1. 导出：`docker cp migrate_chroma.py ragnxus-api:/tmp/` → `docker exec ragnxus-api python /tmp/migrate_chroma.py export /data/chroma_db /tmp/kb_export.json` → `docker cp` 回宿主
2. `docker compose stop rag-api` + `Rename-Item chroma_db chroma_db_old_0.5.17`（备份）
3. build 新镜像 → `docker compose up -d --force-recreate rag-api`（自动建空库，1.5.9 初始化 7 个 init 块）
4. 导入：`docker cp kb_export.json` + `docker exec ... import /data/chroma_db /tmp/kb_export.json`（输出 CLEARED 7 → IMPORTED 190）
5. `docker compose restart rag-api` + 验证 health/query/stream

**数据完整性核对**：旧库 count 222 vs 导入 190 的差异是用户删过数据（count 口径），导出=导入=190 即完整。验证方法：`docker exec ragnxus-api python -c "import json; d=json.load(open('/tmp/kb_export.json')); print(len(d['documents']))"` 对比导入数。

### 13.5 遗留

- 旧镜像 `ragnxus-rag-api:0.5.17-backup`、`chroma_db_old_0.5.17`、`.wheels/` 暂留（回滚保险 + build 弹药），确认稳定后可删
- torch 仍是 pypi 标准版（带 2.5GB CUDA 依赖），以后可换 `+cpu` 变体把镜像砍到 1/4（需 download.pytorch.org 可达，当前网络下未做）
