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

function App() {
  const [tab, setTab] = useState<"qa" | "hybrid">("qa")

  return (
    <div className="app">
      <Sidebar />
      <main className="main-area">
        <TabBar tab={tab} onTabChange={setTab} />
        {tab === "qa" ? <QATab /> : <HybridTab />}
      </main>
    </div>
  )
}

/* ============================
   侧边栏组件
   ============================ */
function Sidebar() {
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

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>RAGNEXUS</h1>
        <span className="badge">v1.3</span>
      </div>

      <div className="status-card">
        <div className="status-row">
          <span className={`dot ${online === true ? "green" : online === false ? "red" : "gray"}`} />
          <span>{online === true ? "服务在线" : online === false ? "连接失败" : "检查中..."}</span>
        </div>
        {online && <p className="kb-meta">知识库：{kbCount} 个块</p>}
      </div>

      <div className="sidebar-section">
        <h3>关于</h3>
        <p>生产级 RAG + Multi-Agent 知识库问答系统。</p>
        <p className="repo-link">
          <a href="https://github.com/inervers/RAGNEXUS" target="_blank">GitHub →</a>
        </p>
      </div>
    </aside>
  )
}

/* ============================
   标签栏
   ============================ */
function TabBar({ tab, onTabChange }: { tab: string; onTabChange: (t: "qa" | "hybrid") => void }) {
  return (
    <div className="tab-bar">
      <button className={`tab-btn ${tab === "qa" ? "active" : ""}`} onClick={() => onTabChange("qa")}>
        💬 问答
      </button>
      <button className={`tab-btn ${tab === "hybrid" ? "active" : ""}`} onClick={() => onTabChange("hybrid")}>
        🔍 混合检索
      </button>
    </div>
  )
}

/* ============================
   问答标签页
   ============================ */
function QATab() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  async function handleSend() {
    if (!input.trim() || loading) return
    const question = input.trim()
    setInput("")
    setMessages((prev) => [...prev, { role: "user", content: question }])
    setLoading(true)

    try {
      const resp = await fetch(`${API_BASE}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify({ question }),
      })
      const data = await resp.json()
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.answer ?? "无回答", sources: data.sources },
      ])
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "请求失败，请检查服务是否运行" }])
    }
    setLoading(false)
  }

  return (
    <div className="tab-content">
      <div className="messages">
        {messages.length === 0 && (
          <div className="welcome">
            <h2>RAGNEXUS 知识库</h2>
            <p>基于检索增强生成的知识库问答系统。输入问题开始对话。</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            <div className="avatar">{msg.role === "user" ? "👤" : "🤖"}</div>
            <div className="bubble">
              <div className="content">{msg.content}</div>
              {msg.sources && msg.sources.length > 0 && (
                <details className="sources">
                  <summary>📚 知识来源（{msg.sources.length} 篇）</summary>
                  {msg.sources.map((src, j) => (
                    <div key={j} className="source-item">
                      <p className="source-query">{src.query}</p>
                      <p className="source-text">{src.content.slice(0, 200)}...</p>
                    </div>
                  ))}
                </details>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="message assistant">
            <div className="avatar">🤖</div>
            <div className="bubble">
              <div className="typing-dots"><span /><span /><span /></div>
            </div>
          </div>
        )}

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
        <button onClick={handleSend} disabled={loading || !input.trim()}>发送</button>
      </div>
    </div>
  )
}

/* ============================
   混合检索标签页
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
      {/* 搜索表单 */}
      <div className="hybrid-form">
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
            召回数量
            <input type="number" min={3} max={50} value={topK}
              onChange={(e) => setTopK(Number(e.target.value))} />
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={useReranker}
              onChange={(e) => setUseReranker(e.target.checked)} />
            Reranker 重排序
          </label>
          <button className="search-btn" onClick={handleSearch} disabled={loading || !query.trim()}>
            {loading ? "检索中..." : "检索"}
          </button>
        </div>
      </div>

      {/* 结果 */}
      {loading && <div className="loading-text">正在检索...</div>}

      {result && (
        <div className="hybrid-results">
          {/* 稠密检索 */}
          <section>
            <h3>📊 稠密向量检索 Top-{result.dense_top.length}</h3>
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

          {/* 混合检索 */}
          <section>
            <h3>🔄 混合检索 Top-{result.hybrid_top.length}</h3>
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

          {/* Reranker */}
          {result.reranked && (
            <section>
              <h3>🎯 Reranker 重排序 Top-{result.reranked.length}</h3>
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
