import { useState, useRef, useEffect, useMemo } from "react"
import "./App.css"

import DotField from "./fxbits/DotField/DotField"
import ShinyText from "./fxbits/ShinyText/ShinyText"
import CountUp from "./fxbits/CountUp/CountUp"
import AnimatedContent from "./fxbits/AnimatedContent/AnimatedContent"
import SpecularButton from "./fxbits/SpecularButton/SpecularButton"
import SpotlightCard from "./fxbits/SpotlightCard/SpotlightCard"
import {
  qaReadinessCopy,
  rerankerDisplay,
  serviceStateFromHealth,
  type RerankerStatus,
  type ServiceState,
} from "./appStatus"
import {
  ApiAuthError,
  ProtectedRequestScope,
  authHeaders,
  clearSessionApiKey,
  ensureApiResponse,
  readSessionApiKey,
  saveSessionApiKey,
} from "./apiAuth"
import {
  FileSelectionGuard,
  buildImportRequest,
  validateSelectedFile,
  type SelectedDocumentFile,
} from "./documentImport"

const API_BASE = ""

type TabKey = "qa" | "hybrid" | "kb" | "agent"
type OnApiError = (error: unknown) => void

interface Message {
  role: "user" | "assistant"
  content: string
  sources?: Source[]
}

interface Source {
  id: string
  query: string
  content: string
}

interface SearchResult {
  id: string
  score?: number
  rrf_score?: number
  ce_score?: number
  text: string
}

const TABS: { key: TabKey; label: string }[] = [
  { key: "qa", label: "问答" },
  { key: "hybrid", label: "混合检索" },
  { key: "kb", label: "知识库" },
  { key: "agent", label: "Agent 写作" },
]

/* fxbits 按钮统一配置（深色科技风） */
const FX_BUTTON = {
  size: "md" as const,
  radius: 4,
  tint: "#3566D6",
  tintOpacity: 1,
  textColor: "#F4F7FF",
  lineColor: "#8FB4FF",
  baseColor: "#3566D6",
  intensity: 1,
  shineSize: 10,
  shineFade: 40,
  thickness: 1,
  speed: 0.35,
  followMouse: true,
  proximity: 250,
  autoAnimate: true,
}

function useProtectedRequestScope(apiKey: string): ProtectedRequestScope {
  const scopeRef = useRef(new ProtectedRequestScope())
  useEffect(() => {
    scopeRef.current.abort()
    return () => scopeRef.current.abort()
  }, [apiKey])
  return scopeRef.current
}

/* ============================================================
   主应用
   ============================================================ */
function App() {
  const [tab, setTab] = useState<TabKey>("qa")
  const [serviceState, setServiceState] = useState<ServiceState>("checking")
  const [kbCount, setKbCount] = useState(0)
  const [authMessage, setAuthMessage] = useState("")
  const [apiKey, setApiKey] = useState(() => {
    try { return readSessionApiKey(sessionStorage) }
    catch { return "" }
  })

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then(async (response) => {
        const payload = await response.json()
        setServiceState(serviceStateFromHealth(response.ok, payload.status))
        setKbCount(response.ok && payload.status === "ok" ? (payload.chunks ?? 0) : 0)
      })
      .catch(() => {
        setServiceState("offline")
        setKbCount(0)
      })
  }, [])

  function handleSaveApiKey(value: string) {
    const saved = saveSessionApiKey(sessionStorage, value)
    setApiKey(saved)
    setAuthMessage("")
  }

  function handleClearApiKey() {
    clearSessionApiKey(sessionStorage)
    setApiKey("")
    setAuthMessage("")
  }

  const handleApiError: OnApiError = (error) => {
    if (error instanceof ApiAuthError) setAuthMessage(error.message)
  }

  return (
    <div className="app">
      <DotField
        dotRadius={1.6}
        dotSpacing={14}
        cursorRadius={320}
        bulgeStrength={70}
        gradientFrom="rgba(53, 102, 214, 0.6)"
        gradientTo="rgba(143, 180, 255, 0.28)"
        glowColor="rgba(53, 102, 214, 0.15)"
        className="bg-field"
      />
      <Sidebar
        tab={tab}
        onTabChange={setTab}
        serviceState={serviceState}
        kbCount={kbCount}
        apiKey={apiKey}
        onSaveApiKey={handleSaveApiKey}
        onClearApiKey={handleClearApiKey}
      />
      <main className="main-area">
        {!apiKey && (
          <div className="auth-banner" role="status">
            受保护操作已锁定：请在侧边栏输入 API Key。Key 仅保存在当前浏览器标签页。
          </div>
        )}
        {apiKey && authMessage && (
          <div className="auth-banner auth-banner-error" role="alert">{authMessage}</div>
        )}
        <div className="tab-content">
          {tab === "qa" && <QATab serviceState={serviceState} apiKey={apiKey} onApiError={handleApiError} />}
          {tab === "hybrid" && <HybridTab apiKey={apiKey} onApiError={handleApiError} />}
          {tab === "kb" && <KBTab apiKey={apiKey} onApiError={handleApiError} />}
          {tab === "agent" && <AgentTab apiKey={apiKey} onApiError={handleApiError} />}
        </div>
      </main>
    </div>
  )
}

/* ============================================================
   侧边栏
   ============================================================ */
function Sidebar({
  tab,
  onTabChange,
  serviceState,
  kbCount,
  apiKey,
  onSaveApiKey,
  onClearApiKey,
}: {
  tab: TabKey
  onTabChange: (t: TabKey) => void
  serviceState: ServiceState
  kbCount: number
  apiKey: string
  onSaveApiKey: (value: string) => void
  onClearApiKey: () => void
}) {
  const [apiKeyDraft, setApiKeyDraft] = useState(apiKey)

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="logo">R</span>
        <ShinyText text="RAGNEXUS" speed={2.5} color="#C6CCD6" shineColor="#9DBDFF" spread={160} className="logo-text" />
        <span className="badge">v0.7</span>
      </div>

      <div className="auth-card">
        <label htmlFor="api-key">API Key</label>
        <input
          id="api-key"
          type="password"
          value={apiKeyDraft}
          onChange={(event) => setApiKeyDraft(event.target.value)}
          placeholder="仅保存在当前标签页"
          autoComplete="off"
        />
        <div className="auth-actions">
          <button
            type="button"
            onClick={() => onSaveApiKey(apiKeyDraft)}
            disabled={!apiKeyDraft.trim()}
          >
            保存
          </button>
          {apiKey && (
            <button
              type="button"
              className="auth-clear"
              onClick={() => { setApiKeyDraft(""); onClearApiKey() }}
            >
              清除
            </button>
          )}
        </div>
        <span>{apiKey ? "已配置 · session only" : "未配置"}</span>
      </div>

      <div className="status-card">
        <div className="status-row">
          <span className={`dot ${serviceState === "online" ? "green" : serviceState === "offline" ? "red" : "gray"}`} />
          <span>{serviceState === "online" ? "服务在线" : serviceState === "offline" ? "连接失败" : "检查中..."}</span>
        </div>
        {serviceState === "online" && (
          <div className="kb-meta">
            <CountUp from={0} to={kbCount} duration={1} /> 个知识块
          </div>
        )}
      </div>

      <nav className="sidebar-nav">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`nav-btn ${tab === t.key ? "active" : ""}`}
            onClick={() => onTabChange(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        <a href="/design-showcase.html" target="_blank" rel="noopener">设计展示</a>
        <a href="https://github.com/inervers/RAGNEXUS" target="_blank" rel="noopener">GitHub</a>
      </div>
    </aside>
  )
}

/* ============================================================
   问答标签页
   ============================================================ */
function QATab({
  serviceState,
  apiKey,
  onApiError,
}: {
  serviceState: ServiceState
  apiKey: string
  onApiError: OnApiError
}) {
  const [messages, setMessages] = useState<Message[]>(() => {
    try { return JSON.parse(localStorage.getItem("ragnxus_chat") || "[]") }
    catch { return [] }
  })
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // 打字动画
  const typingBufRef = useRef("")
  const typedLenRef = useRef(0)
  const typingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopTyping(fillRemaining = false) {
    if (typingTimerRef.current) {
      clearInterval(typingTimerRef.current)
      typingTimerRef.current = null
    }
    if (fillRemaining && typingBufRef.current.length > typedLenRef.current) {
      const buf = typingBufRef.current
      setMessages((prev) => {
        const copy = [...prev]
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i]?.role === "assistant") {
            copy[i] = { ...copy[i], content: buf }
            break
          }
        }
        return copy
      })
    }
  }

  function feedTyping(text: string) {
    typingBufRef.current += text
  }

  function startTyping() {
    stopTyping()
    typedLenRef.current = 0
    const SPEED = 25
    typingTimerRef.current = setInterval(() => {
      const buf = typingBufRef.current
      const target = Math.min(typedLenRef.current + 1, buf.length)
      if (target > typedLenRef.current) {
        typedLenRef.current = target
        const display = buf.slice(0, target)
        setMessages((prev) => {
          const copy = [...prev]
          // 找最后一个 assistant 消息，避免用 stale index
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i]?.role === "assistant") {
              copy[i] = { ...copy[i], content: display }
              break
            }
          }
          return copy
        })
      }
    }, SPEED)
  }

  // 读写 localStorage
  const msgRef = useRef(messages)
  msgRef.current = messages
  function save() {
    try { localStorage.setItem("ragnxus_chat", JSON.stringify(msgRef.current)) } catch {}
  }

  const requestScope = useProtectedRequestScope(apiKey)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  async function handleSend() {
    if (!apiKey || !input.trim() || loading) return
    const q = input.trim()
    setInput("")
    // 添加用户消息
    setMessages((prev) => [...prev, { role: "user", content: q }])
    setLoading(true)

    // 添加一个空的助手消息
    setMessages((prev) => [...prev, { role: "assistant", content: "" }])

    // 重置打字缓冲区
    typingBufRef.current = ""
    typedLenRef.current = 0

    const signal = requestScope.begin()

    try {
      const resp = await fetch(`${API_BASE}/query/stream`, {
        method: "POST",
        headers: authHeaders(apiKey, { "Content-Type": "application/json" }),
        body: JSON.stringify({ question: q }),
        signal,
      })
      await ensureApiResponse(resp)

      const reader = resp.body?.getReader()
      if (!reader) { setLoading(false); return }

      const decoder = new TextDecoder()
      let buf = ""
      let sourcesData: Source[] | null = null

      // 启动打字动画
      startTyping()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buf += decoder.decode(value, { stream: true })
        const lines = buf.split("\n")
        buf = lines.pop() || ""

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          try {
            const evt = JSON.parse(line.slice(6))
            if (evt.type === "token") {
              feedTyping(evt.content)
            }
            if (evt.type === "done" && evt.sources) {
              sourcesData = evt.sources
            }
          } catch { /* ignore */ }
        }
      }

      // 流结束：停止动画，填上剩余文字
      stopTyping(true)
      if (sourcesData) {
        setMessages((prev) => {
          const copy = [...prev]
          const last = copy[copy.length - 1]
          if (last?.role === "assistant") {
            copy[copy.length - 1] = { ...last, sources: sourcesData }
          }
          return copy
        })
      }
    } catch (error: unknown) {
      if (error instanceof Error && error.name === "AbortError") {
        stopTyping(true)
        setMessages((prev) => {
          const copy = [...prev]
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i]?.role === "assistant") {
              const c = copy[i].content
              copy[i] = { ...copy[i], content: c ? c + "\n\n[已取消]" : "[已取消]" }
              break
            }
          }
          return copy
        })
      } else {
        onApiError(error)
        stopTyping(true)
        setMessages((prev) => {
          const copy = [...prev]
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i]?.role === "assistant" && !copy[i].content) {
              copy[i] = {
                ...copy[i],
                content: error instanceof ApiAuthError ? error.message : "请求失败",
              }
              break
            }
          }
          return copy
        })
      }
    }
    setLoading(false)
    save()
  }

  return (
    <div className="qa-layout">
      <div className="messages" id="qa-scroll">
        {messages.length === 0 && (
          <AnimatedContent distance={20} duration={0.6} threshold={0.05} container="#qa-scroll" className="welcome-wrap">
            <div className="welcome">
              <div className="welcome-kicker">{qaReadinessCopy(serviceState).kicker}</div>
              <div className="welcome-title">
                <span className="welcome-dot" />
                {qaReadinessCopy(serviceState).title}
              </div>
              <p className="welcome-sub">{qaReadinessCopy(serviceState).subtitle}</p>
            </div>
          </AnimatedContent>
        )}
        {messages.length > 0 && (
          <div className="chat-toolbar">
            <span className="chat-count">{messages.length} 条消息</span>
            <button className="btn-clear" onClick={() => { try { localStorage.removeItem("ragnxus_chat") } catch {}; setMessages([]) }}>清空</button>
          </div>
        )}

        {messages.map((msg, i) => {
          const isStreaming = msg.role === "assistant" && !msg.content
          return (
          <div key={i} className={`message ${msg.role}`}>
            <div className="msg-meta">
              <span className="msg-role">{msg.role === "user" ? "USER" : "RAG"}</span>
              <span className="msg-prompt">{msg.role === "user" ? "❯" : "↳"}</span>
            </div>
            <div className="msg-body">
              {isStreaming ? (
                <div className="typing"><span /><span /><span /></div>
              ) : (
                <p className="msg-content">{msg.content}</p>
              )}
              {msg.sources && msg.sources.length > 0 && (
                <details className="sources">
                  <summary>sources / {msg.sources.length}</summary>
                  {msg.sources.map((src, j) => (
                    <div key={src.id || j} className="source-row">
                      <code className="source-id">{src.id}</code>
                      <code className="source-query">{src.query}</code>
                      <p className="source-text">{src.content.slice(0, 180)}</p>
                    </div>
                  ))}
                </details>
              )}
            </div>
          </div>
          )
        })}

        <div ref={bottomRef} />
      </div>

      <div className="input-bar">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
          placeholder="输入问题..."
          disabled={loading}
        />
        {loading ? (
          <button className="btn-cancel" onClick={() => requestScope.abort()}>
            取消
          </button>
        ) : (
          <SpecularButton {...FX_BUTTON} onClick={handleSend} disabled={!apiKey || !input.trim()}>
            发送
          </SpecularButton>
        )}
      </div>
    </div>
  )
}

/* ============================================================
   混合检索标签页
   ============================================================ */
function HybridTab({ apiKey, onApiError }: { apiKey: string; onApiError: OnApiError }) {
  const [query, setQuery] = useState("")
  const [topK, setTopK] = useState(10)
  const [useReranker, setUseReranker] = useState(true)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{
    dense_top: SearchResult[]
    hybrid_top: SearchResult[]
    reranked?: SearchResult[]
    reranker_status?: RerankerStatus
  } | null>(null)
  const [expanded, setExpanded] = useState<{ group: string; doc: SearchResult } | null>(null)
  const requestScope = useProtectedRequestScope(apiKey)

  async function handleSearch() {
    if (!apiKey || !query.trim() || loading) return
    setLoading(true)
    setResult(null)
    try {
      const signal = requestScope.begin()
      const resp = await fetch(`${API_BASE}/query/hybrid`, {
        method: "POST",
        headers: authHeaders(apiKey, { "Content-Type": "application/json" }),
        body: JSON.stringify({ question: query.trim(), top_k: topK, use_reranker: useReranker }),
        signal,
      })
      await ensureApiResponse(resp)
      setResult((await resp.json()).result ?? null)
    } catch (error) {
      onApiError(error)
      setResult(null)
    }
    setLoading(false)
  }

  return (
    <div className="hybrid-layout" id="hybrid-scroll">
      <div className="search-panel">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="输入查询..."
          disabled={loading}
        />
        <div className="search-options">
          <label>召回 <input type="number" min={3} max={50} value={topK}
            onChange={(e) => setTopK(+e.target.value)} /></label>
          <label className="checkbox">
            <input type="checkbox" checked={useReranker}
              onChange={(e) => setUseReranker(e.target.checked)} />
            Reranker
          </label>
          <SpecularButton {...FX_BUTTON} onClick={handleSearch} disabled={!apiKey || loading || !query.trim()}>
            {loading ? "检索中" : "检索"}
          </SpecularButton>
        </div>
      </div>

      {loading && <p className="loading-text">检索中...</p>}

      {result && (
        <div className="search-results">
          {rerankerDisplay(result.reranker_status) && (
            <div className={`reranker-status reranker-status--${rerankerDisplay(result.reranker_status)?.mode}`}>
              <strong>{rerankerDisplay(result.reranker_status)?.title}</strong>
              <span>{rerankerDisplay(result.reranker_status)?.message}</span>
            </div>
          )}
          {(
            [
              { title: "稠密向量检索", items: result.dense_top, key: "score" as const },
              { title: "混合检索（RRF）", items: result.hybrid_top, key: "rrf_score" as const },
              ...(result.reranked ? [{ title: rerankerDisplay(result.reranker_status)?.title ?? "Reranker", items: result.reranked, key: "ce_score" as const }] : []),
            ] as const
          ).map((g) => (
            <AnimatedContent key={g.title} distance={16} duration={0.5} threshold={0.05} container="#hybrid-scroll">
              <section className="result-group">
                <h3>{g.title}</h3>
                <div className="result-list">
                  {g.items.map((doc, i) => {
                    const isExpanded = expanded?.group === g.title && expanded?.doc.id === doc.id
                    return (
                      <div key={i}>
                        <SpotlightCard
                          spotlightColor="rgba(143, 180, 255, 0.08)"
                          className={`result-item${isExpanded ? " result-item-active" : ""}`}
                          onClick={() => setExpanded(isExpanded ? null : { group: g.title, doc })}
                        >
                          <div className="result-meta">
                            <span className="result-num">#{i + 1}</span>
                            <code className="result-id">{doc.id}</code>
                            <span className="result-score">{doc[g.key]?.toFixed(4)}</span>
                          </div>
                          <Pct v={doc[g.key] ?? 0} />
                          <p className="result-text">{doc.text.slice(0, 160)}</p>
                        </SpotlightCard>
                      </div>
                    )
                  })}
                </div>
              </section>
            </AnimatedContent>
          ))}
        </div>
      )}

      {expanded && (
        <div className="preview-modal" onClick={() => setExpanded(null)}>
          <div className="preview-modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="preview-modal-header">
              <span className="preview-modal-title">{expanded.group} — {expanded.doc.id}</span>
              <button className="btn-close" onClick={() => setExpanded(null)}>关闭</button>
            </div>
            <pre className="preview-modal-body">{expanded.doc.text}</pre>
          </div>
        </div>
      )}
    </div>
  )
}

function Pct({ v }: { v: number }) {
  const w = Math.max(0, Math.min(100, v * 100))
  return <div className="pct-bar"><div className="pct-fill" style={{ width: `${w}%` }} /></div>
}

/* ============================================================
   知识库管理标签页
   ============================================================ */
const PAGE_SIZE = 30

interface KbRecord {
  id: string
  source: string
  document: string
}

interface KbGroup {
  source: string
  ids: string[]
  chunks: string[]
}

function KBTab({ apiKey, onApiError }: { apiKey: string; onApiError: OnApiError }) {
  const [records, setRecords] = useState<KbRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [title, setTitle] = useState("")
  const [content, setContent] = useState("")
  const [docPage, setDocPage] = useState(0)
  const [previewIdx, setPreviewIdx] = useState<number | null>(null)
  const [statusMsg, setStatusMsg] = useState("")
  const [uploadProgress, setUploadProgress] = useState(0)
  const [selectedFile, setSelectedFile] = useState<SelectedDocumentFile | null>(null)
  const [kbSearch, setKbSearch] = useState("")
  const [deleting, setDeleting] = useState<string | null>(null)
  const requestScope = useProtectedRequestScope(apiKey)
  const fileSelection = useRef(new FileSelectionGuard())

  const groups = useMemo<KbGroup[]>(() => {
    const map = new Map<string, KbGroup>()
    for (const r of records) {
      const key = r.source || "未命名"
      const g = map.get(key)
      if (g) {
        g.ids.push(r.id)
        g.chunks.push(r.document)
      } else {
        map.set(key, { source: key, ids: [r.id], chunks: [r.document] })
      }
    }
    return [...map.values()]
  }, [records])

  const filteredGroups = useMemo(() => {
    if (!kbSearch.trim()) return groups
    const q = kbSearch.toLowerCase()
    return groups.filter((g) =>
      g.source.toLowerCase().includes(q) || g.chunks.some((c) => c.toLowerCase().includes(q))
    )
  }, [groups, kbSearch])

  useEffect(() => {
    if (apiKey) fetchDocs()
    else setRecords([])
  }, [apiKey])

  async function fetchDocs() {
    try {
      const signal = requestScope.begin()
      const resp = await fetch(`${API_BASE}/kb/docs`, {
        headers: authHeaders(apiKey),
        signal,
      })
      await ensureApiResponse(resp)
      const data = await resp.json()
      setRecords(data.records ?? [])
    } catch (error) { onApiError(error) }
  }

  async function handleAdd() {
    if (!apiKey || !title.trim() || !content.trim()) return
    setLoading(true)
    setStatusMsg("正在检查并添加...")
    try {
      const signal = requestScope.begin()
      const resp = await fetch(`${API_BASE}/doc`, {
        method: "POST",
        headers: authHeaders(apiKey, { "Content-Type": "application/json" }),
        body: JSON.stringify({ title: title.trim(), content: content.trim() }),
        signal,
      })
      await ensureApiResponse(resp)
      const data = await resp.json()
      setStatusMsg(data.message || "添加完成")
      setTitle("")
      setContent("")
      await fetchDocs()
    } catch (e) {
      onApiError(e)
      setStatusMsg(e instanceof Error ? `添加失败：${e.message}` : "添加失败，请重试")
    }
    setLoading(false)
  }

  async function handleImport() {
    if (!apiKey || !selectedFile) return
    setLoading(true)
    setStatusMsg("正在导入完整文档...")
    try {
      const signal = requestScope.begin()
      const resp = await fetch(`${API_BASE}/doc/import`, {
        method: "POST",
        headers: authHeaders(apiKey, { "Content-Type": "application/json" }),
        body: JSON.stringify(buildImportRequest(selectedFile)),
        signal,
      })
      await ensureApiResponse(resp)
      const data = await resp.json()
      setStatusMsg(`${data.message}；完整导入 ${data.parsed_length} 字符`)
      fileSelection.current.invalidate()
      setSelectedFile(null)
      await fetchDocs()
    } catch (error) {
      onApiError(error)
      setStatusMsg(error instanceof Error ? `导入失败：${error.message}` : "导入失败，请重试")
    }
    setLoading(false)
  }

  async function handleDelete(g: KbGroup) {
    if (!apiKey || deleting) return
    if (!window.confirm(`删除文档「${g.source}」？（共 ${g.ids.length} 个分块）`)) return
    setDeleting(g.source)
    try {
      const signal = requestScope.begin()
      const resp = await fetch(`${API_BASE}/kb/docs/delete`, {
        method: "POST",
        headers: authHeaders(apiKey, { "Content-Type": "application/json" }),
        body: JSON.stringify({ ids: g.ids }),
        signal,
      })
      await ensureApiResponse(resp)
      const data = await resp.json()
      setStatusMsg(`已删除 ${data.deleted} 个块，剩余 ${data.remaining}`)
      setPreviewIdx(null)
      await fetchDocs()
    } catch (error) {
      onApiError(error)
      setStatusMsg(error instanceof Error ? `删除失败：${error.message}` : "删除失败，请重试")
    }
    setDeleting(null)
  }

  async function fillFromFile(f: File) {
    const selection = fileSelection.current.begin()
    setSelectedFile(null)
    const validationError = validateSelectedFile(f)
    if (validationError) {
      setStatusMsg(validationError)
      setUploadProgress(0)
      setLoading(false)
      return
    }
    setStatusMsg("读取文件...")
    setUploadProgress(5)
    setLoading(true)
    try {
      const b64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onprogress = (event) => {
          if (fileSelection.current.isCurrent(selection) && event.lengthComputable) {
            setUploadProgress(5 + Math.round(event.loaded / event.total * 35))
          }
        }
        reader.onload = () => {
          const bytes = new Uint8Array(reader.result as ArrayBuffer)
          let binary = ""
          for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
          resolve(btoa(binary))
        }
        reader.onerror = () => reject(reader.error)
        reader.readAsArrayBuffer(f)
      })
      if (!fileSelection.current.isCurrent(selection)) return
      setUploadProgress(45)
      setStatusMsg("发送到服务器预览...")
      const signal = requestScope.begin()
      const resp = await fetch(`${API_BASE}/doc/preview`, {
        method: "POST",
        headers: authHeaders(apiKey, { "Content-Type": "application/json" }),
        body: JSON.stringify({ filename: f.name, content: b64 }),
        signal,
      })
      await ensureApiResponse(resp)
      if (!fileSelection.current.isCurrent(selection)) return
      setUploadProgress(75)
      const data = await resp.json()
      if (!fileSelection.current.isCurrent(selection)) return
      setSelectedFile({
        filename: f.name,
        encodedContent: b64,
        title: data.title,
        preview: data.preview,
        fullLength: data.full_length,
        truncated: data.truncated,
      })
      setUploadProgress(100)
      setStatusMsg(`预览完成（共 ${data.full_length} 字符，正式导入使用原始文件）`)
    } catch (error) {
      if (!fileSelection.current.isCurrent(selection)) return
      onApiError(error)
      setStatusMsg(error instanceof Error ? `解析失败：${error.message}` : "解析失败，请重试")
    }
    if (fileSelection.current.isCurrent(selection)) {
      setUploadProgress(0)
      setLoading(false)
    }
  }

  return (
    <div className="kb-layout">
      <div className="kb-add">
        <h3>添加文档</h3>
        <input value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="标题" />
        <textarea value={content} onChange={(e) => setContent(e.target.value)}
          placeholder="内容" rows={8} />
        <SpecularButton {...FX_BUTTON} onClick={handleAdd}
          disabled={loading || !title.trim() || !content.trim()}>
          {loading ? "添加中..." : "添加"}
        </SpecularButton>

        <h3 style={{ marginTop: 24 }}>导入文件</h3>
        <div className="upload-zone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            const f = e.dataTransfer.files[0]
            if (f) fillFromFile(f)
          }}
          onClick={() => document.getElementById("file-input")?.click()}>
          <span className="upload-hint">拖拽文件到此处，或点击选择</span>
        </div>
        {uploadProgress > 0 && (
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${uploadProgress}%` }} />
          </div>
        )}
        <input id="file-input" type="file" accept=".pdf,.txt"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null
            if (f) fillFromFile(f)
          }} />
        {selectedFile && (
          <div className="kb-preview">
            <div className="kb-preview-header">
              <span>{selectedFile.title} · {selectedFile.fullLength} 字符</span>
              <button className="btn-close" onClick={() => {
                fileSelection.current.invalidate()
                setSelectedFile(null)
              }}>清除</button>
            </div>
            <p className="kb-preview-text">{selectedFile.preview}</p>
            {selectedFile.truncated && (
              <p className="upload-msg">这里只展示前 5000 字符；正式导入会重新解析完整文件。</p>
            )}
            <SpecularButton {...FX_BUTTON} onClick={handleImport} disabled={loading}>
              {loading ? "导入中..." : "导入完整文档"}
            </SpecularButton>
          </div>
        )}
        {statusMsg && <p className="upload-msg">{statusMsg}</p>}
      </div>

      <div className="kb-list">
        <h3>全部文档（{groups.length} 篇 / {records.length} 块）</h3>
        <input className="kb-search" value={kbSearch} onChange={(e) => { setKbSearch(e.target.value); setDocPage(0); setPreviewIdx(null) }}
          placeholder="搜索文档内容..." />
        <div className="kb-page-controls">
          {(() => {
            const totalPages = Math.ceil(filteredGroups.length / PAGE_SIZE) || 1
            return <>
              <button className="btn-page" disabled={docPage === 0} onClick={() => { setDocPage(p => p - 1); setPreviewIdx(null) }}>上一页</button>
              <span className="kb-page-info">
                <input className="page-jump" type="number" min={1} max={totalPages}
                  value={docPage + 1}
                  onChange={(e) => {
                    const n = parseInt(e.target.value)
                    if (n > 0 && n <= totalPages) {
                      setDocPage(n - 1)
                      setPreviewIdx(null)
                    }
                  }} />
                <span>/ {totalPages}</span>
              </span>
              <button className="btn-page" disabled={(docPage + 1) * PAGE_SIZE >= filteredGroups.length} onClick={() => { setDocPage(p => p + 1); setPreviewIdx(null) }}>下一页</button>
            </>
          })()}
        </div>
        <div className="kb-items">
          {filteredGroups.slice(docPage * PAGE_SIZE, (docPage + 1) * PAGE_SIZE).map((g, i) => {
            const gi = docPage * PAGE_SIZE + i
            const isActive = previewIdx === gi
            return (
              <div key={g.source}
                className={`kb-item ${isActive ? "active" : ""}`}
                onClick={() => setPreviewIdx(isActive ? null : gi)}>
                <span className="kb-item-title">{g.source}</span>
                <span className="kb-item-count">{g.ids.length} 块</span>
                <button className="kb-item-del" onClick={(e) => { e.stopPropagation(); handleDelete(g) }}>
                  {deleting === g.source ? "删除中" : "删除"}
                </button>
                <span className="kb-item-arrow">{isActive ? "﹀" : "▶"}</span>
                <p className="kb-item-desc">{g.chunks[0].slice(0, 90)}</p>
              </div>
            )
          })}
          {filteredGroups.length === 0 && <p className="empty-text">{kbSearch ? "无匹配文档" : "知识库为空"}</p>}
        </div>
        {previewIdx !== null && filteredGroups[previewIdx] && (
          <div className="kb-preview">
            <div className="kb-preview-header">
              <span>文档「{filteredGroups[previewIdx].source}」（{filteredGroups[previewIdx].ids.length} 块）</span>
              <button className="btn-close" onClick={() => setPreviewIdx(null)}>关闭</button>
            </div>
            {filteredGroups[previewIdx].chunks.map((c, j) => (
              <div key={j} className="kb-preview-chunk">
                <div className="kb-preview-chunk-idx">块 #{j + 1}</div>
                <p className="kb-preview-text">{c}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ============================================================
   Multi-Agent 写作标签页
   ============================================================ */
function AgentTab({ apiKey, onApiError }: { apiKey: string; onApiError: OnApiError }) {
  const [topic, setTopic] = useState("")
  const [maxRetries, setMaxRetries] = useState(2)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<Record<string, any> | null>(null)
  const requestScope = useProtectedRequestScope(apiKey)

  async function handleStart() {
    if (!apiKey || !topic.trim() || loading) return
    setLoading(true)
    setResult(null)
    try {
      const signal = requestScope.begin()
      const resp = await fetch(`${API_BASE}/agent/write`, {
        method: "POST",
        headers: authHeaders(apiKey, { "Content-Type": "application/json" }),
        body: JSON.stringify({ topic: topic.trim(), max_retries: maxRetries }),
        signal,
      })
      await ensureApiResponse(resp)
      const data = await resp.json()
      setResult(data.result ?? null)
    } catch (error) {
      onApiError(error)
      setResult(null)
    }
    setLoading(false)
  }

  return (
    <div className="agent-layout" id="agent-scroll">
      <div className="agent-form">
        <h3>写作流水线</h3>
        <p className="agent-desc">研究员 → 写作者 → 审核员，三阶段 Agent 协作生成文章。</p>
        <input value={topic} onChange={(e) => setTopic(e.target.value)}
          placeholder="输入主题..." disabled={loading} />
        <div className="agent-options">
          <label>最大重试 <input type="number" min={1} max={5} value={maxRetries}
            onChange={(e) => setMaxRetries(+e.target.value)} /></label>
          <SpecularButton {...FX_BUTTON} onClick={handleStart}
            disabled={!apiKey || loading || !topic.trim()}>
            {loading ? "写作中..." : "开始写作"}
          </SpecularButton>
        </div>
      </div>

      {loading && <p className="loading-text">Agent 正在协作写作...</p>}

      {result && (
        <AnimatedContent distance={16} duration={0.5} threshold={0.05} container="#agent-scroll">
          <div className="agent-output">
            <div className="agent-metrics">
              <div className={`metric-badge ${result.passed ? "pass" : "fail"}`}>
                {result.passed ? "通过" : "未通过"}
              </div>
              <div className="metric"><span className="metric-val">{result.rating}/5</span>评分</div>
              <div className="metric"><span className="metric-val">{result.attempts}</span>尝试</div>
              <div className="metric"><span className="metric-val">{result.duration_s}s</span>耗时</div>
            </div>

            {result.article ? (
              <div className="agent-article">
                <h4>生成文章</h4>
                <div className="article-body">
                  {(() => {
                    try {
                      const art = JSON.parse(result.article)
                      return <div>
                        <h5>{art.title}</h5>
                        <p>{(art.content ?? "").slice(0, 2000)}</p>
                      </div>
                    } catch {
                      return <p>{result.article.slice(0, 2000)}</p>
                    }
                  })()}
                </div>
              </div>
            ) : (
              <p className="empty-text">本次未生成文章内容，请重试。</p>
            )}

            {result.monitor?.agent_metrics && (
              <div className="agent-monitor">
                <h4>Agent 监控</h4>
                <div className="monitor-grid">
                  {Object.entries(result.monitor.agent_metrics).map(([name, m]: any) => (
                    <div key={name} className="monitor-card">
                      <strong>{name}</strong>
                      <div className="monitor-stats">
                        <span>{m.calls} 次调用</span>
                        <span>平均 {m.avg_duration_s}s</span>
                        <span>成功率 {m.success}/{m.calls}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </AnimatedContent>
      )}
    </div>
  )
}

export default App
