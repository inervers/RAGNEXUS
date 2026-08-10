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

const API_BASE = ""
const API_KEY = "rag-secret-key-2024"

type TabKey = "qa" | "hybrid" | "kb" | "agent"

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

/* ============================================================
   主应用
   ============================================================ */
function App() {
  const [tab, setTab] = useState<TabKey>("qa")
  const [serviceState, setServiceState] = useState<ServiceState>("checking")
  const [kbCount, setKbCount] = useState(0)

  useEffect(() => {
    fetch(`${API_BASE}/health`, {
      headers: { "X-API-Key": API_KEY },
    })
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
      />
      <main className="main-area">
        <div className="tab-content">
          {tab === "qa" && <QATab serviceState={serviceState} />}
          {tab === "hybrid" && <HybridTab />}
          {tab === "kb" && <KBTab />}
          {tab === "agent" && <AgentTab />}
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
}: {
  tab: TabKey
  onTabChange: (t: TabKey) => void
  serviceState: ServiceState
  kbCount: number
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="logo">R</span>
        <ShinyText text="RAGNEXUS" speed={2.5} color="#C6CCD6" shineColor="#9DBDFF" spread={160} className="logo-text" />
        <span className="badge">v0.7</span>
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
function QATab({ serviceState }: { serviceState: ServiceState }) {
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

  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  async function handleSend() {
    if (!input.trim() || loading) return
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

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const resp = await fetch(`${API_BASE}/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify({ question: q }),
        signal: controller.signal,
      })

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
    } catch (e: any) {
      if (e?.name === "AbortError") {
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
        stopTyping(true)
        setMessages((prev) => {
          const copy = [...prev]
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i]?.role === "assistant" && !copy[i].content) {
              copy[i] = { ...copy[i], content: "请求失败" }
              break
            }
          }
          return copy
        })
      }
    }
    setLoading(false)
    abortRef.current = null
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
          <button className="btn-cancel" onClick={() => abortRef.current?.abort()}>
            取消
          </button>
        ) : (
          <SpecularButton {...FX_BUTTON} onClick={handleSend} disabled={!input.trim()}>
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
function HybridTab() {
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

  async function handleSearch() {
    if (!query.trim() || loading) return
    setLoading(true)
    setResult(null)
    try {
      const resp = await fetch(`${API_BASE}/query/hybrid`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify({ question: query.trim(), top_k: topK, use_reranker: useReranker }),
      })
      setResult((await resp.json()).result ?? null)
    } catch { setResult(null) }
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
          <SpecularButton {...FX_BUTTON} onClick={handleSearch} disabled={loading || !query.trim()}>
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

function KBTab() {
  const [records, setRecords] = useState<KbRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [title, setTitle] = useState("")
  const [content, setContent] = useState("")
  const [docPage, setDocPage] = useState(0)
  const [previewIdx, setPreviewIdx] = useState<number | null>(null)
  const [statusMsg, setStatusMsg] = useState("")
  const [uploadProgress, setUploadProgress] = useState(0)
  const [kbSearch, setKbSearch] = useState("")
  const [deleting, setDeleting] = useState<string | null>(null)

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

  useEffect(() => { fetchDocs() }, [])

  async function fetchDocs() {
    try {
      const resp = await fetch(`${API_BASE}/kb/docs`, {
        headers: { "X-API-Key": API_KEY },
      })
      const data = await resp.json()
      setRecords(data.records ?? [])
    } catch { /* ignore */ }
  }

  async function handleAdd() {
    if (!title.trim() || !content.trim()) return
    setLoading(true)
    setStatusMsg("正在检查并添加...")
    try {
      const resp = await fetch(`${API_BASE}/doc`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify({ title: title.trim(), content: content.trim() }),
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || data.error || "添加失败")
      setStatusMsg(data.message || "添加完成")
      setTitle("")
      setContent("")
      await fetchDocs()
    } catch (e) {
      setStatusMsg(e instanceof Error ? `添加失败：${e.message}` : "添加失败，请重试")
    }
    setLoading(false)
  }

  async function handleDelete(g: KbGroup) {
    if (deleting) return
    if (!window.confirm(`删除文档「${g.source}」？（共 ${g.ids.length} 个分块）`)) return
    setDeleting(g.source)
    try {
      const resp = await fetch(`${API_BASE}/kb/docs/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify({ ids: g.ids }),
      })
      const data = await resp.json()
      setStatusMsg(`已删除 ${data.deleted} 个块，剩余 ${data.remaining}`)
      setPreviewIdx(null)
      await fetchDocs()
    } catch {
      setStatusMsg("删除失败，请重试")
    }
    setDeleting(null)
  }

  async function fillFromFile(f: File) {
    const ext = f.name.split(".").pop()?.toLowerCase()
    if (ext === "txt") {
      const reader = new FileReader()
      reader.onload = () => {
        const text = reader.result as string
        setTitle(f.name.replace(/\.txt$/i, ""))
        setContent(text.slice(0, 5000))
      }
      reader.readAsText(f)
      return
    }
    if (ext === "pdf") {
      setStatusMsg("读取文件...")
      setUploadProgress(5)
      setLoading(true)
      try {
        // 用 FileReader 读取并追踪进度
        const b64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onprogress = (e) => {
            if (e.lengthComputable) {
              setUploadProgress(5 + Math.round(e.loaded / e.total * 35))
            }
          }
          reader.onload = () => {
            const bytes = new Uint8Array(reader.result as ArrayBuffer)
            let bin = ""
            for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
            resolve(btoa(bin))
          }
          reader.onerror = () => reject(reader.error)
          reader.readAsArrayBuffer(f)
        })
        setUploadProgress(45)
        setStatusMsg("发送到服务器...")
        const resp = await fetch(`${API_BASE}/doc/preview`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
          body: JSON.stringify({ filename: f.name, content: b64 }),
        })
        setUploadProgress(75)
        setStatusMsg("正在解析...")
        if (!resp.ok) {
          const err = await resp.text()
          setStatusMsg(`解析失败：${err}`)
        } else {
          const data = await resp.json()
          setTitle(data.title)
          setContent(data.content)
          setUploadProgress(100)
          setStatusMsg(`解析完成（共 ${data.full_length} 字符）`)
        }
      } catch (e) {
        setStatusMsg("解析失败，请重试")
      }
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
function AgentTab() {
  const [topic, setTopic] = useState("")
  const [maxRetries, setMaxRetries] = useState(2)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<Record<string, any> | null>(null)

  async function handleStart() {
    if (!topic.trim() || loading) return
    setLoading(true)
    setResult(null)
    try {
      const resp = await fetch(`${API_BASE}/agent/write`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify({ topic: topic.trim(), max_retries: maxRetries }),
      })
      const data = await resp.json()
      setResult(data.result ?? null)
    } catch { setResult(null) }
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
            disabled={loading || !topic.trim()}>
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
