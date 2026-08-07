"""L5-Day3: FC RAG API + 结构化日志（API Key + 限流 + 全链路追踪）

- 鉴权：X-API-Key 请求头
- 限流：滑动窗口（配置 RAG_RATE_LIMIT）
- 日志：trace_id 追踪、工具调用链路、请求耗时、错误记录
"""

import sys, os, json, random, base64

# Windows user-site 兼容（Docker 中直接跳过）
_REAL_USER_SITE = os.environ.get("PYTHON_USER_SITE")
if _REAL_USER_SITE and os.path.isdir(_REAL_USER_SITE) and _REAL_USER_SITE not in sys.path:
    sys.path.insert(0, _REAL_USER_SITE)

# HF_HOME 在 Docker 中通过 docker-compose.yml 设置，本地环境请手动设置环境变量或从 .env 加载
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

# =============================================
# 配置加载（从 .env + 环境变量）
# =============================================

CONFIG = {}

def _load_config():
    search_dir = os.path.dirname(__file__)
    for _ in range(6):
        env_path = os.path.join(search_dir, ".env")
        if os.path.isfile(env_path):
            for line in open(env_path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    CONFIG[k] = v
                    os.environ.setdefault(k, v)
            break
        parent = os.path.dirname(search_dir)
        if parent == search_dir:
            break
        search_dir = parent

_load_config()

# LLM 配置：优先 DeepSeek，兼容智谱 key
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY")
LLM_API_KEY = DEEPSEEK_API_KEY or ZHIPU_API_KEY
# 未显式指定 LLM_BASE_URL / LLM_MODEL 时，按 key 类型选默认值
LLM_BASE_URL = os.environ.get("LLM_BASE_URL",
                              "https://api.deepseek.com" if DEEPSEEK_API_KEY else "https://open.bigmodel.cn/api/paas/v4")
LLM_MODEL = os.environ.get("LLM_MODEL",
                           "deepseek-v4-flash" if DEEPSEEK_API_KEY else "glm-4.7-flash")
RAG_API_KEY = os.environ.get("RAG_API_KEY", "rag-secret-key-2024")
RATE_LIMIT = int(os.environ.get("RAG_RATE_LIMIT", "30"))

if not LLM_API_KEY:
    print("需要设置 DEEPSEEK_API_KEY（推荐）或 ZHIPU_API_KEY")
    exit(1)

import time, uuid, logging, traceback
import httpx
from transformers import AutoTokenizer, AutoModel
import torch
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import chromadb
from chromadb.api.types import EmbeddingFunction

# =============================================
# 结构化日志（终端 + 文件）
# =============================================

LOG_FILE = os.environ.get("RAG_LOG_FILE", os.path.join(os.path.dirname(__file__), "rag_api.log"))

logger = logging.getLogger("rag-api")
logger.setLevel(logging.INFO)

# 终端 handler（stderr）
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-5s | %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(console)

# 文件 handler（追加，UTF-8）
file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-5s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(file_handler)

def _log(trace_id: str, event: str, **fields):
    """结构化日志：一行一个事件，json 字段便于 grep"""
    parts = [f"[{trace_id[:8]}]", event]
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    logger.info(" | ".join(parts))

def _log_tool(trace_id: str, func_name: str, args: dict, result_preview: str):
    _log(trace_id, "tool_call", tool=func_name, args=json.dumps(args, ensure_ascii=False), result=result_preview[:80])

# =============================================
# 速率限制器
# =============================================

WINDOW_SEC = 60

class RateLimiter:
    def __init__(self):
        self._records: dict[str, list[float]] = {}

    def check(self, key: str) -> tuple[bool, int, int]:
        now = time.time()
        window_start = now - WINDOW_SEC
        if key not in self._records:
            self._records[key] = []
        self._records[key] = [t for t in self._records[key] if t > window_start]
        used = len(self._records[key])
        if used >= RATE_LIMIT:
            return False, used, RATE_LIMIT
        self._records[key].append(now)
        return True, used + 1, RATE_LIMIT

rate_limiter = RateLimiter()

# =============================================
# 统一中间件（鉴权 + 限流 + 日志追踪）
# =============================================

AUTH_HEADER = "X-API-Key"
TRACE_HEADER = "X-Trace-Id"

async def logging_middleware(request: Request, call_next):
    """最外层中间件：追踪、耗时、错误记录"""
    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)
    start = time.time()

    _log(trace_id, "request", method=request.method, path=request.url.path)

    try:
        response = await call_next(request)
        duration = round(time.time() - start, 3)
        response.headers["X-Trace-Id"] = trace_id
        if response.status_code < 400:
            _log(trace_id, "response", status=response.status_code, duration=f"{duration}s")
        else:
            _log(trace_id, "response_error", status=response.status_code, duration=f"{duration}s")
        return response
    except Exception as e:
        duration = round(time.time() - start, 3)
        tb = traceback.format_exc()
        _log(trace_id, "unhandled_error", error=str(e), duration=f"{duration}s")
        logger.error(f"[{trace_id[:8]}] Unhandled:\n{tb}")
        return JSONResponse(status_code=500, content={"error": "Internal server error", "trace_id": trace_id})


async def security_middleware(request: Request, call_next):
    """安全检查（鉴权 → 限流）"""
    if request.url.path == "/health" or request.method == "OPTIONS":
        return await call_next(request)

    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)

    # 鉴权
    api_key = request.headers.get(AUTH_HEADER)
    if not api_key:
        _log(trace_id, "auth_failed", reason="missing_key")
        return JSONResponse(status_code=401, content={"error": "Missing X-API-Key header"})
    if api_key != RAG_API_KEY:
        _log(trace_id, "auth_failed", reason="invalid_key")
        return JSONResponse(status_code=403, content={"error": "Invalid API Key"})

    # 限流
    allowed, used, limit = rate_limiter.check(api_key)
    if not allowed:
        _log(trace_id, "rate_limited", used=used, limit=limit)
        return JSONResponse(
            status_code=429,
            content={"error": f"Rate limit exceeded: {used}/{limit} per minute"},
            headers={"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0"},
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(limit - used)
    return response

# =============================================
# 嵌入模型
# =============================================
tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2", local_files_only=True)
model = AutoModel.from_pretrained("sentence-transformers/all-MiniLM-L6-v2", local_files_only=True)

def embed_texts(texts):
    inputs = tokenizer(texts, truncation=True, padding=True, return_tensors="pt", max_length=256)
    with torch.no_grad():
        pooled = model(**inputs).last_hidden_state.mean(dim=1)
    return (pooled / torch.norm(pooled, dim=1, keepdim=True)).numpy()

class MiniLMEmbedding(EmbeddingFunction):
    """适配 ChromaDB 1.x：需实现 __init__ 与 name()，query 输入可能是 Document 对象。"""

    def __init__(self):
        pass

    def __call__(self, input):
        # 1.x 的 query 输入可能是 Document 对象列表（带 .text），统一提取
        if isinstance(input, (list, tuple)):
            texts = [d.text if hasattr(d, "text") else d for d in input]
        else:
            texts = [input]
        return [e.tolist() for e in embed_texts(texts)]

    def name(self) -> str:
        return "MiniLM-L6-v2-mean-pooling"

# =============================================
# Chroma 持久化
# =============================================
CHROMA_DIR = os.environ.get("RAG_CHROMA_DIR", os.path.join(os.path.dirname(__file__), "chroma_db"))
client = chromadb.PersistentClient(path=CHROMA_DIR, settings=chromadb.config.Settings(anonymized_telemetry=False))
collection = client.get_or_create_collection(name="rag_knowledge", embedding_function=MiniLMEmbedding())
splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=20)

def _doc_count() -> int:
    try:
        return collection.count()
    except:
        return 0

def _doc_ids(start: int, n: int) -> list[str]:
    return [f"doc_{start + i}" for i in range(n)]

if _doc_count() == 0:
    init_texts = [
        "Python was created by Guido van Rossum and first released in 1991. It is a high-level general-purpose programming language emphasizing code readability with significant indentation.",
        "PyTorch was developed by Meta AI (Facebook AI Research) and released in 2016. Key features include dynamic computation graphs, GPU-accelerated tensor computation, automatic differentiation with Autograd.",
        "The Transformer architecture was introduced by Google in the 2017 paper 'Attention Is All You Need'. It is the foundation for BERT, GPT, T5, and ViT.",
        "RAG (Retrieval-Augmented Generation) combines a retriever and a generator. The retriever searches a knowledge base for relevant documents to produce informed answers.",
        "Chroma is an open-source vector database built for AI applications. It supports persistent storage and integrates natively with LangChain and LlamaIndex.",
        "LangChain is an open-source framework for LLM application development. It provides modular abstractions for models, prompts, chains, memory, agents, and retrieval.",
    ]
    chunks = splitter.split_documents([Document(t) for t in init_texts])
    ids = _doc_ids(1, len(chunks))
    collection.add(ids=ids, documents=[c.page_content for c in chunks], metadatas=[{"source": "init"} for _ in chunks])
    logger.info(f"初始化知识库：{len(chunks)} 个块")
else:
    logger.info(f"知识库已加载：{_doc_count()} 个块")

# =============================================
# LLM 客户端：120s 读超时（智谱免费版单并发+高峰期间响应慢）
llm_client = httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0), trust_env=False)


def _llm_post(body: dict) -> dict:
    """带 429/超时重试的 LLM POST，返回响应 JSON。"""
    for attempt in range(4):
        try:
            r = llm_client.post(f"{LLM_BASE_URL}/chat/completions",
                json=body, headers={"Authorization": f"Bearer {LLM_API_KEY}"})
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < 3:
                wait = 2 * (attempt + 1) + random.random()
                time.sleep(wait)
                continue
            raise
        except httpx.TimeoutException:
            if attempt < 3:
                time.sleep(1 + random.random())
                continue
            raise
    raise RuntimeError("LLM 请求失败")

def call_llm(messages, tools=None):
    body = {
        "model": LLM_MODEL, "messages": messages,
        "temperature": 0.3, "stream": False,
    }
    if tools:
        body["tools"] = tools
    return _llm_post(body)["choices"][0]["message"]

def _deepseek_ask(system: str, user: str) -> str:
    body = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
    }
    return _llm_post(body)["choices"][0]["message"]["content"]

# =============================================
# 工具定义 + 实现
# =============================================

TOOLS = [
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": "搜索知识库（向量语义检索），查找与问题相关的文档",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "add_document",
        "description": "向知识库添加一条新知识",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["title", "content"]},
    }},
    {"type": "function", "function": {
        "name": "summarize",
        "description": "对一段文本进行摘要总结",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "translate",
        "description": "将文本翻译为目标语言",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "target_language": {"type": "string"}}, "required": ["text", "target_language"]},
    }},
]

SEARCH_N_RESULTS = 3

# 混合检索权重（生产与评测统一口径 = sparse 偏关键词）。
# 2026-08-07 全量评测（40 题 × 4 路，零 token）：
#   hybrid 1.0/1.0: R@5 0.39 MRR 0.58 Hit@5 0.72
#   hybrid 1.0/2.0: R@5 0.47 MRR 0.68 Hit@5 0.88  ← 胜出，定为此口径
# 注意：原生产 sparse=2.0 与评测 1.0/1.0 不一致，曾导致评测数字低估真实能力。
HYBRID_DENSE_WEIGHT = 1.0
HYBRID_SPARSE_WEIGHT = 2.0


def _tool_search(query: str) -> str:
    hs = _get_hybrid_search()
    result = hs.search(query, top_k=SEARCH_N_RESULTS * 2,
                       dense_weight=HYBRID_DENSE_WEIGHT, sparse_weight=HYBRID_SPARSE_WEIGHT)
    hybrid = result.get("hybrid_top", [])
    if hybrid:
        return "\n".join(item["text"] for item in hybrid)
    # 回退纯向量
    results = collection.query(query_texts=[query], n_results=SEARCH_N_RESULTS)
    docs = results.get("documents", [[]])[0]
    return "\n".join(docs) if docs else "未找到相关信息"


def _tool_search_chunks(query: str) -> list:
    hs = _get_hybrid_search()
    result = hs.search(query, top_k=SEARCH_N_RESULTS * 2,
                       dense_weight=HYBRID_DENSE_WEIGHT, sparse_weight=HYBRID_SPARSE_WEIGHT)
    hybrid = result.get("hybrid_top", [])
    if hybrid:
        return [item["text"] for item in hybrid]
    # 回退纯向量
    results = collection.query(query_texts=[query], n_results=SEARCH_N_RESULTS)
    return results.get("documents", [[]])[0]

def _tool_add(title: str, content: str) -> str:
    full = f"{title}：{content}"
    chunks = splitter.split_documents([Document(full)])
    ids = _doc_ids(_doc_count() + 1, len(chunks))
    collection.add(ids=ids, documents=[c.page_content for c in chunks], metadatas=[{"source": title} for _ in chunks])
    # 标记语料过期，下次 hybrid 查询会重建 BM25
    global _corpus_version
    _corpus_version = -1
    return f"添加成功（{len(chunks)} 个分块），共 {_doc_count()} 个块"

def _tool_summarize(text: str) -> str:
    return _deepseek_ask("You are a summarizer.", f"Summarize:\n\n{text}")

def _tool_translate(text: str, target: str) -> str:
    return _deepseek_ask(f"Translate to {target}. Output only the translation.", text)

TOOL_IMPLS = {
    "search_knowledge": _tool_search,
    "add_document": _tool_add,
    "summarize": _tool_summarize,
    "translate": _tool_translate,
}

SYSTEM_PROMPT = (
    "You are an AI assistant with a knowledge base.\n"
    "Available tools: search_knowledge, add_document, summarize, translate.\n"
    "Rules:\n"
    "1. FOR TECHNICAL QUESTIONS, use search_knowledge first.\n"
    "2. For chat, answer directly.\n"
    "3. When asked to SUMMARIZE, call summarize.\n"
    "4. When asked to TRANSLATE, call translate.\n"
    "5. Answer in the same language as the user."
)

def rag_with_fc(query: str, trace_id: str = uuid.uuid4().hex) -> dict:
    _log(trace_id, "rag_start", query=query[:80])
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": query}]
    tool_rounds = 0
    sources = []
    for _ in range(8):
        msg = call_llm(msgs, tools=TOOLS)
        if not msg.get("tool_calls"):
            _log(trace_id, "rag_done", rounds=tool_rounds)
            return {"answer": msg["content"], "sources": sources}
        msgs.append({"role": "assistant", "content": msg.get("content"), "tool_calls": msg["tool_calls"]})
        for tc in msg["tool_calls"]:
            fname = tc["function"]["name"]
            fargs = json.loads(tc["function"]["arguments"] or "{}")
            result = TOOL_IMPLS[fname](**fargs)
            _log_tool(trace_id, fname, fargs, result)
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})
            if fname == "search_knowledge" and result and result != "未找到相关信息":
                sources.append({"query": fargs.get("query", ""), "content": result[:300]})
            tool_rounds += 1
    _log(trace_id, "rag_max_rounds", rounds=tool_rounds)
    return {"answer": msgs[-1].get("content", ""), "sources": sources}

async def stream_rag(query: str, trace_id: str):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": query}]
    for _ in range(8):
        msg = call_llm(msgs, tools=TOOLS)
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fname = tc["function"]["name"]
                fargs = json.loads(tc["function"]["arguments"] or "{}")
                yield f"data: {json.dumps({'type': 'tool', 'name': fname, 'args': fargs})}\n\n"
            msgs.append({"role": "assistant", "content": msg.get("content"), "tool_calls": msg["tool_calls"]})
            for tc in msg["tool_calls"]:
                fname = tc["function"]["name"]
                fargs = json.loads(tc["function"]["arguments"] or "{}")
                result = TOOL_IMPLS[fname](**fargs)
                _log_tool(trace_id, fname, fargs, result)
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})
            continue
        body = {
            "model": LLM_MODEL, "messages": msgs,
            "temperature": 0.3, "stream": True,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), trust_env=False) as ac:
            async with ac.stream("POST", f"{LLM_BASE_URL}/chat/completions",
                json=body, headers={"Authorization": f"Bearer {LLM_API_KEY}"}) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    delta = json.loads(data)["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
        break
    yield f"data: {json.dumps({'type': 'done'})}\n\n"

# =============================================
# FastAPI 应用
# =============================================

app = FastAPI(title="RAG Agent API (Production)", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(logging_middleware)
app.middleware("http")(security_middleware)

class QueryRequest(BaseModel):
    question: str

class DocRequest(BaseModel):
    title: str
    content: str

class UploadDocRequest(BaseModel):
    filename: str
    content: str

class DeleteDocsRequest(BaseModel):
    ids: list[str]

class HybridQueryRequest(BaseModel):
    question: str
    top_k: int = 10
    dense_weight: float = 1.0
    sparse_weight: float = 1.0
    use_reranker: bool = False

class AgentWriteRequest(BaseModel):
    topic: str
    max_retries: int = 1

@app.post("/doc/preview")
def preview_doc(req: UploadDocRequest, request: Request):
    """解析 PDF/TXT 并返回文本（不写入知识库），供前端预览后手动确认"""
    if not req.filename.strip() or not req.content.strip():
        raise HTTPException(400, "文件名和内容不能为空")
    ext = req.filename.rsplit(".", 1)[-1].lower() if "." in req.filename else ""
    try:
        raw_bytes = base64.b64decode(req.content)
    except Exception:
        raise HTTPException(400, "Base64 解码失败")
    if ext == "pdf":
        try:
            from pdf_parser import extract_text
            parsed = extract_text(raw_bytes)
            text = parsed["text"]
            title = req.filename.rsplit(".", 1)[0]
        except Exception as e:
            raise HTTPException(500, f"PDF 解析失败：{e}")
    elif ext == "txt":
        text = raw_bytes.decode("utf-8", errors="replace")
        title = req.filename.rsplit(".", 1)[0]
    else:
        raise HTTPException(400, f"不支持的文件格式：.{ext}（仅支持 pdf/txt）")
    return {"title": title, "content": text[:5000], "full_length": len(text)}

@app.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "chunks": _doc_count(),
        "tools": list(TOOL_IMPLS.keys()),
        "auth_required": True,
        "rate_limit": f"{RATE_LIMIT}/min",
        "version": "0.7.1",
    }

@app.post("/query")
def query(req: QueryRequest, request: Request):
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")
    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)

    # 混合检索（稠密向量 + BM25 稀疏 + RRF 融合），偏关键词权重
    kb_chunks = _tool_search_chunks(req.question)
    context_parts = ["## 知识库检索结果（请基于此回答）"]
    for i, chunk in enumerate(kb_chunks):
        context_parts.append(f"--- 文档 {i+1} ---\n{chunk}")
    context_parts.append(f"\n## 用户问题\n{req.question}")
    context = "\n".join(context_parts)

    result = rag_with_fc(context, trace_id)
    sources = result.get("sources", [])
    if not sources and kb_chunks:
        sources = [{"query": req.question[:80], "content": c[:300]} for c in kb_chunks]

    return {"answer": result["answer"], "sources": sources, "trace_id": trace_id}

@app.post("/query/stream")
async def query_stream(req: QueryRequest, request: Request):
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")
    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)
    return StreamingResponse(
        stream_rag(req.question, trace_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache", "Connection": "keep-alive",
            "X-Accel-Buffering": "no", "X-Trace-Id": trace_id,
        },
    )

@app.post("/doc")
def add_doc(req: DocRequest, request: Request):
    if not req.title.strip() or not req.content.strip():
        raise HTTPException(400, "标题和内容不能为空")
    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)
    result = _tool_add(req.title, req.content)
    _log(trace_id, "doc_added", title=req.title[:40], chunks=result)
    return {"message": result, "total_chunks": _doc_count(), "trace_id": trace_id}

# =============================================
# 高级检索（Hybrid + Reranker）
# =============================================

_hybrid_search = None
_reranker = None
_corpus_version = 0

def _get_hybrid_search():
    global _hybrid_search, _corpus_version
    current_count = _doc_count()
    if _hybrid_search is None:
        from rag_advanced import HybridSearch
        all_docs = collection.get()
        corpus = all_docs.get("documents", [])
        _hybrid_search = HybridSearch(collection, embed_texts, corpus)
        _corpus_version = current_count
    elif _corpus_version != current_count:
        # 知识库有新增文档，重建 BM25 索引
        all_docs = collection.get()
        corpus = all_docs.get("documents", [])
        _hybrid_search.set_corpus(corpus)
        _corpus_version = current_count
        logger.info(f"HybridSearch 语料刷新：{current_count} 个文档")
    return _hybrid_search

def _get_reranker():
    global _reranker
    if _reranker is None:
        from rag_advanced import Reranker
        _reranker = Reranker()
    return _reranker

@app.get("/kb/docs")
def list_kb_docs(request: Request):
    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)
    all_docs = collection.get()
    docs = all_docs.get("documents", [])
    ids = all_docs.get("ids", [])
    metas = all_docs.get("metadatas", [])
    records = [
        {
            "id": ids[i],
            "document": docs[i],
            "source": metas[i].get("source", "") if isinstance(metas[i], dict) else "",
        }
        for i in range(len(docs))
    ]
    _log(trace_id, "kb_list", count=len(docs))
    return {"count": len(docs), "documents": docs, "records": records, "trace_id": trace_id}

@app.post("/kb/docs/delete")
def delete_kb_docs(req: DeleteDocsRequest, request: Request):
    if not req.ids:
        raise HTTPException(400, "ids 不能为空")
    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)
    all_docs = collection.get()
    existing = set(all_docs.get("ids", []))
    to_delete = [i for i in req.ids if i in existing]
    missing = [i for i in req.ids if i not in existing]
    if to_delete:
        collection.delete(ids=to_delete)
    global _corpus_version
    _corpus_version = -1
    _log(trace_id, "kb_delete", deleted=len(to_delete), missing=len(missing))
    return {
        "deleted": len(to_delete),
        "missing": missing,
        "remaining": _doc_count(),
        "trace_id": trace_id,
    }

@app.post("/query/hybrid")
def hybrid_query(req: HybridQueryRequest, request: Request):
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")
    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)
    _log(trace_id, "hybrid_query", query=req.question[:80])
    hs = _get_hybrid_search()
    result = hs.search(query=req.question, top_k=req.top_k,
                       dense_weight=req.dense_weight, sparse_weight=req.sparse_weight)
    if req.use_reranker:
        reranker = _get_reranker()
        candidates = result["dense_top"] + result.get("hybrid_top", [])
        result["reranked"] = reranker.rerank(req.question, candidates, top_k=5)
        _log(trace_id, "reranker_done", candidates=len(candidates))
    _log(trace_id, "hybrid_done", dense=len(result["dense_top"]),
         hybrid=len(result["hybrid_top"]))
    return {"result": result, "trace_id": trace_id}

# =============================================
# Multi-Agent 编排
# =============================================

def _kb_search(query: str, top_k: int = 5) -> list[dict]:
    """知识库检索函数，注入到 MultiAgentWorkflow 供研究员使用。"""
    try:
        hs = _get_hybrid_search()
        raw = hs.search(query=query, top_k=top_k)
        hybrid = raw.get("hybrid_top", [])
        # 如果混合结果太少，补上稠密结果
        if len(hybrid) < 3:
            dense = raw.get("dense_top", [])
            seen = set(d.get("id") for d in hybrid)
            for d in dense:
                if d["id"] not in seen:
                    hybrid.append(d)
                    seen.add(d["id"])
        return hybrid[:top_k]
    except Exception:
        return []


@app.post("/agent/write")
def agent_write(req: AgentWriteRequest, request: Request):
    if not req.topic.strip():
        raise HTTPException(400, "主题不能为空")
    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)
    _log(trace_id, "agent_write_start", topic=req.topic[:40])
    from rag_multiagent import MultiAgentWorkflow
    wf = MultiAgentWorkflow(api_key=LLM_API_KEY,
                            base_url=LLM_BASE_URL,
                            model=LLM_MODEL,
                            knowledge_fn=_kb_search)
    result = wf.run(req.topic, max_retries=req.max_retries)
    _log(trace_id, "agent_write_done", passed=str(result["passed"]),
         rating=result["rating"], attempts=result["attempts"],
         duration=f"{result['duration_s']}s",
         kb_docs=result.get("kb_docs", 0))
    return {"result": result, "trace_id": trace_id}

if __name__ == "__main__":
    import uvicorn
    logger.info("=" * 50)
    logger.info("RAG Agent API (Production v0.7.0)")
    logger.info(f"API Key 鉴权：启用")
    logger.info(f"速率限制：{RATE_LIMIT} 次/分钟")
    logger.info(f"知识库：{_doc_count()} 个块")
    logger.info(f"结构化日志：启用")
    logger.info(f"用法：X-API-Key header + X-Trace-Id header(可选)")
    logger.info("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
