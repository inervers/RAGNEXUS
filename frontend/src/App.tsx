import { useState, useRef, useEffect } from "react"
import "./App.css"

const API_BASE = "/api"
const API_KEY = "rag-secret-key-2024"

interface Message {
  role: "user" | "assistant"
  content: string
  sources?: { query: string; content: string }[]
}

interface SearchResult {
  id: string
  score?: number
  rrf_score?: number
  ce_score?: number
  text: string
}

type TabKey = "qa" | "hybrid"

function App() {
  const [tab, setTab] = useState<TabKey>("qa")

  return (
    <div className="app">
      <Sidebar tab={tab} onTabChange={setTab} />
      <main className="main-area">
        {tab === "qa" ? <QATab /> : <HybridTab />}
      </main>
    </div>
  )
}

/* ============================
   侧边栏（导航 + 状态）
   ============================ */
function Sidebar({ tab, onTabChange }: { tab: TabKey; onTabChange: (t: TabKey) => void }) {
  const [online, setOnline] = useState<boolean | null>(null)
  const [kbCount, setKbCount] = useState(0)

  useEffect(() => {
    fetch(`${API_BASE}/health`, {
      headers: { "X-API-Key": API_KEY },
    })
      .then((r) => r.json())
      .then((d) => { setOnline(true); setKbCount(d.chunks ?? 0) })
      .catch(() => setOnline(false))
  }, [])

  const navItems: { key: TabKey; label: string }[] = [
    { key: "qa", label: "qa" },
    { key: "hybrid", label: "hybrid" },
  ]

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>RAGNEXUS</h1>
        <span className="badge">v1.3</span>
      </div>

      <nav className="sidebar-nav">
        <p className="nav-label">// navigation</p>
        {navItems.map((item) => (
          <button
            key={item.key}
            className={`nav-btn ${tab === item.key ? "active" : ""}`}
            onClick={() => onTabChange(item.key)}
          >
            ./{item.label}
          </button>
        ))}
      </nav>

      <div className="status-card">
        <div className="status-row">
          <span className={`dot ${online === true ? "green" : online === false ? "red" : "gray"}`} />
          <span>{online === true ? "服务在线" : online === false ? "连接失败" : "检查中..."}</span>
        </div>
        {online && <p className="kb-meta">知识库：{kbCount} 个块</p>}
      </div>

      <div className="sidebar-section">
        <h3>// about</h3>
        <p>生产级 RAG + Multi-Agent 知识库问答系统。</p>
        <p className="repo-link">
          <a href="https://github.com/inervers/RAGNEXUS" target="_blank" rel="noreferrer">
            github.com/inervers/RAGNEXUS
          </a>
        </p>
      </div>
    </aside>
  )
}

/* ============================
   问答（日志流）
   ============================ */
function QATab() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [streamText, setStreamText] = useState("")
  const [activeTools, setActiveTools] = useState<string[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streamText, activeTools])

  function cancel() {
    abortRef.current?.abort()
  }

  async function handleSend() {
    if (!input.trim() || loading) return
    const question = input.trim()
    setInput("")
    setMessages((prev) => [...prev, { role: "user", content: question }])
    setLoading(true)
    setStreamText("")
    setActiveTools([])

    const controller = new AbortController()
    abortRef.current = controller

    let full = ""
    let sources: { query: string; content: string }[] = []

    try {
      const resp = await fetch(`${API_BASE}/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify({ question }),
        signal: controller.signal,
      })

      if (!resp.ok) {
        const errText = await resp.text()
        throw new Error(`HTTP ${resp.status}: ${errText.slice(0, 200)}`)
      }

      const reader = resp.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      if (reader) {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const blocks = buffer.split("\n\n")
          buffer = blocks.pop() ?? ""

          for (const block of blocks) {
            const line = block.trim()
            if (!line.startsWith("data: ")) continue
            const payload = line.slice(6)
            try {
              const obj = JSON.parse(payload)
              if (obj.type === "tool") {
                setActiveTools((prev) => [...prev, `${obj.name}(${JSON.stringify(obj.args)})`])
              } else if (obj.type === "token" && obj.content) {
                full += obj.content
                setStreamText(full)
              } else if (obj.type === "done") {
                // done
              }
            } catch { /* ignore malformed */ }
          }
        }
      }

      setMessages((prev) => [...prev, { role: "assistant", content: full || "（无回答）", sources }])
    } catch (err: unknown) {
      const e = err as Error
      if (e.name !== "AbortError") {
        setMessages((prev) => [...prev, { role: "assistant", content: `请求失败：${e.message}` }])
      }
    }

    setStreamText("")
    setActiveTools([])
    setLoading(false)
  }

  return (
    <div className="tab-content qa-tab">
      <div className="log-stream">
        {messages.length === 0 && !loading && (
          <div className="welcome">
            <p className="welcome-prompt">$ ragnxus --start</p>
            <p>RAG 知识库问答系统。输入问题开始对话。</p>
            <p className="welcome-hint">// 支持流式输出、知识来源追溯、混合检索</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`log-entry ${msg.role}`}>
            <div className="msg-meta">
              <span className="msg-prefix">{msg.role === "user" ? "USER" : "RAG"}</span>
              <span className="msg-caret">{msg.role === "user" ? "❯" : "↳"}</span>
            </div>
            <div className="msg-body">
              <pre className="msg-content">{msg.content}</pre>
              {msg.sources && msg.sources.length > 0 && (
                <details className="sources">
                  <summary>[source] 知识来源（{msg.sources.length} 篇）</summary>
                  {msg.sources.map((src, j) => (
                    <div key={j} className="source-item">
                      <p className="source-query">$ {src.query}</p>
                      <p className="source-text">{src.content.slice(0, 240)}</p>
                    </div>
                  ))}
                </details>
              )}
            </div>
          </div>
        ))}

        {activeTools.length > 0 && (
          <div className="tool-log">
            {activeTools.map((t, i) => (
              <p key={i} className="tool-line">tool ▸ {t}</p>
            ))}
          </div>
        )}

        {loading && (
          <div className="log-entry assistant">
            <div className="msg-meta">
              <span className="msg-prefix">RAG</span>
              <span className="msg-caret">↳</span>
            </div>
            <div className="msg-body">
              <pre className="msg-content">{streamText}<span className="cursor-block" /></pre>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="input-bar">
        <span className="input-prompt">❯</span>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
          placeholder="输入问题..."
          disabled={loading}
        />
        {loading ? (
          <button className="send-btn cancel-btn" onClick={cancel}>取消</button>
        ) : (
          <button className="send-btn" onClick={handleSend} disabled={!input.trim()}>发送</button>
        )}
      </div>
    </div>
  )
}

/* ============================
   混合检索
   ============================ */
function HybridTab() {
  const [query, setQuery] = useState("")
  const [topK, setTopK] = useState(10)
  const [useReranker, setUseReranker] = useState(true)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{
    dense_top: SearchResult[]
    hybrid_top: SearchResult[]
    reranked?: SearchResult[]
  } | null>(null)

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
      const data = await resp.json()
      setResult(data.result ?? null)
    } catch {
      setResult(null)
    }
    setLoading(false)
  }

  function ScoreBar({ score }: { score: number }) {
    const pct = Math.max(0, Math.min(100, score * 100))
    return (
      <div className="score-bar">
        <div className="score-fill" style={{ width: `${pct}%` }} />
      </div>
    )
  }

  return (
    <div className="tab-content hybrid-tab">
      <div className="hybrid-form">
        <span className="input-prompt">❯</span>
        <input
          className="hybrid-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="输入查询内容..."
          disabled={loading}
        />
        <div className="hybrid-controls">
          <label>
            top_k
            <input type="number" min={3} max={50} value={topK}
              onChange={(e) => setTopK(Number(e.target.value))} />
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={useReranker}
              onChange={(e) => setUseReranker(e.target.checked)} />
            reranker
          </label>
          <button className="search-btn" onClick={handleSearch} disabled={loading || !query.trim()}>
            {loading ? "检索中..." : "检索"}
          </button>
        </div>
      </div>

      {loading && <div className="loading-text">// 正在检索...</div>}

      {result && (
        <div className="hybrid-results">
          <section>
            <h3># dense 稠密向量 Top-{result.dense_top.length}</h3>
            {result.dense_top.map((doc, i) => (
              <div key={i} className="result-card">
                <div className="result-header">
                  <span className="result-id">#{i + 1} {doc.id}</span>
                  <span className="result-score">{doc.score?.toFixed(4)}</span>
                </div>
                <ScoreBar score={doc.score ?? 0} />
                <p className="result-text">{doc.text.slice(0, 150)}</p>
              </div>
            ))}
          </section>

          <section>
            <h3># hybrid 混合检索 Top-{result.hybrid_top.length}</h3>
            {result.hybrid_top.map((doc, i) => (
              <div key={i} className="result-card">
                <div className="result-header">
                  <span className="result-id">#{i + 1} {doc.id}</span>
                  <span className="result-score">RRF {doc.rrf_score?.toFixed(4)}</span>
                </div>
                <ScoreBar score={doc.rrf_score ?? 0} />
                <p className="result-text">{doc.text.slice(0, 150)}</p>
              </div>
            ))}
          </section>

          {result.reranked && (
            <section>
              <h3># rerank 重排序 Top-{result.reranked.length}</h3>
              {result.reranked.map((doc, i) => (
                <div key={i} className="result-card">
                  <div className="result-header">
                    <span className="result-id">#{i + 1} {doc.id}</span>
                    <span className="result-score">CE {doc.ce_score?.toFixed(4)}</span>
                  </div>
                  <ScoreBar score={doc.ce_score ?? 0} />
                  <p className="result-text">{doc.text.slice(0, 150)}</p>
                </div>
              ))}
            </section>
          )}
        </div>
      )}
    </div>
  )
}

export default App
