# RAGNEXUS 运维笔记

> 2026-07-31 实战沉淀：Docker 前端部署 + 后端排障 + LLM 切换的全套经验。
> 下次遇到同类问题，按这份手册走，不要重新踩坑。

---

## 1. 部署基本盘

| 服务 | 端口 | 说明 |
|---|---|---|
| rag-api | 8000 | FastAPI 后端（bind mount 挂载 rag_api.py / rag_multiagent.py，改代码 `restart` 即生效） |
| rag-frontend | 8080 | nginx 静态站点（前端改代码必须 **重新 build** 镜像，restart 不够） |

```powershell
cd C:\Users\inervers\Desktop\OH-WorkSpace\rag-agent-api

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
