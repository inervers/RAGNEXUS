"""
rag_app.py — RAG Agent API 前端界面（Streamlit）
================================================
连接本地或远程 RAGNEXUS API 服务。
支持：文档上传、标准问答、混合检索、Multi-Agent 写作。
"""

import streamlit as st
import httpx
import json
import os
from pathlib import Path

from security_config import load_api_key_from_sources

# =============================================
# 页面配置
# =============================================

st.set_page_config(
    page_title="RAG Agent 知识库",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 加载自定义 CSS（用 UTF-8 编码避免 Windows 中文系统 GBK 报错）
css_path = Path(__file__).parent / "style.css"
if css_path.exists():
    with open(css_path, encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
API_KEY = load_api_key_from_sources(os.environ, Path(__file__).resolve().with_name(".env"))
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


# =============================================
# 工具函数
# =============================================

def api_get(path: str):
    try:
        r = httpx.get(f"{API_BASE}{path}", headers=HEADERS, timeout=10)
        return r.json() if r.status_code == 200 else {"error": r.text}
    except Exception as e:
        return {"error": str(e)}


def api_post(path: str, body: dict):
    try:
        r = httpx.post(f"{API_BASE}{path}", json=body, headers=HEADERS, timeout=60)
        return r.json() if r.status_code == 200 else {"error": r.text}
    except Exception as e:
        return {"error": str(e)}


def show_json(obj: dict, label=None):
    st.code(json.dumps(obj, ensure_ascii=False, indent=2), language="json")


# =============================================
# 侧边栏
# =============================================

with st.sidebar:
    st.title("RAG Agent")
    st.caption("生产级 RAG + Multi-Agent 演示")
    st.markdown(
        "<div style='display:flex;gap:4px;margin-bottom:12px'>"
        "<span style='font-size:11px;padding:2px 8px;border-radius:4px;"
        "background:#EFF6FF;color:#2563EB;font-weight:500'>設計系統 v1</span>"
        "</div>",
        unsafe_allow_html=True
    )

    st.divider()
    st.subheader("🔗 服务连接")
    st.text_input("API 地址", value=API_BASE, key="api_base", label_visibility="collapsed")

    health = api_get("/health")
    if isinstance(health, dict) and "error" not in health:
        st.success(f"服务在线 · v{health.get('version', '?')}")
        st.caption(f"知识库：{health.get('chunks', 0)} 个块  ·  速率限制：{health.get('rate_limit', '?')}")
    else:
        st.error(f"连接失败：{health.get('error', '未知')}")
        st.stop()

    st.divider()
    st.caption("📍 接口")
    kb_docs = api_get("/kb/docs")
    count = len(kb_docs.get("documents", [])) if isinstance(kb_docs, dict) else 0
    st.metric("知识库文档数", count)


# =============================================
# 主界面 - 选项卡
# =============================================

tab1, tab2, tab3, tab4 = st.tabs(["知识库管理", "标准问答", "混合检索", "Multi-Agent"])

# =====================
# Tab1: 知识库管理
# =====================

with tab1:
    st.subheader("上传文档")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("**手动添加**")
        title = st.text_input("标题", key="manual_title")
        content = st.text_area("内容", height=200, key="manual_content")
        if st.button("添加", use_container_width=True, type="primary"):
            if title and content:
                resp = api_post("/doc", {"title": title, "content": content})
                if "error" in resp:
                    st.error(resp["error"])
                else:
                    st.success(resp.get("message", "添加成功"))
                    st.rerun()
            else:
                st.warning("标题和内容不能为空")

    with col2:
        st.markdown("**上传文件**")
        st.caption("支持 .txt / .pdf 格式")
        uploaded = st.file_uploader("选择文件", type=["txt", "pdf"], label_visibility="collapsed")
        if uploaded:
            from pdf_parser import parse_pdf_with_ocr
            raw = uploaded.read()

            if uploaded.name.endswith(".pdf"):
                result = parse_pdf_with_ocr(raw)

                st.info(f"📄 {result['summary']}")

                if result["is_scanned"]:
                    if result.get("ocr_used"):
                        st.info("🔍 该 PDF 是扫描件，已通过 OCR 识别文字")
                    else:
                        st.warning("⚠️ 该 PDF 是扫描件，没有可提取的文字层。")
                        st.warning("💡 配置百度 OCR 可自动识别：在 .env 中添加 BAIDU_OCR_API_KEY 和 BAIDU_OCR_SECRET_KEY")
                        st.stop()

                if result["has_tables"]:
                    st.success(f"提取到 {len(result['tables'])} 个表格，已转为 Markdown 格式")
                    with st.expander("预览表格"):
                        for t in result["tables"]:
                            st.markdown(f"**第 {t['page']} 页 · 表格 {t['table_index']+1}（{t['rows']}行×{t['cols']}列）**")
                            st.markdown(t["markdown"])

                text = result["text"]
                if result["has_tables"]:
                    table_block = "\n\n## 表格数据\n\n"
                    table_block += "\n\n".join(t["markdown"] for t in result["tables"])
                    text += table_block
            else:
                text = raw.decode("utf-8", errors="ignore")

            title = Path(uploaded.name).stem
            with st.expander(f"预览文本（共 {len(text)} 字）", expanded=False):
                # 表格 OCR 结果用 markdown 渲染，普通文本用 textarea
                if "| --- |" in text:
                    st.markdown(text[:800] + ("..." if len(text) > 800 else ""))
                else:
                    st.text(text[:800] + ("..." if len(text) > 800 else ""))

            if st.button("确认添加", key="confirm_upload", type="primary", use_container_width=True):
                resp = api_post("/doc", {"title": title, "content": text})
                if "error" in resp:
                    st.error(resp["error"])
                else:
                    st.success(f"《{title}》已添加（{len(text)} 字符）")
                    st.rerun()

    st.divider()
    st.subheader("知识库全部文档")

    if isinstance(kb_docs, dict) and "documents" in kb_docs:
        docs = kb_docs["documents"]
        if docs:
            for i, d in enumerate(docs):
                with st.expander(f"文档 #{i}（{len(d.split())} 词）"):
                    st.text(d[:500] + ("..." if len(d) > 500 else ""))
        else:
            st.info("知识库为空，请先上传文档")
    else:
        st.warning("无法获取知识库列表")

# =====================
# Tab2: 标准问答
# =====================

with tab2:
    st.subheader("标准问答")
    st.caption("Function Calling 驱动，自动检索知识库 + LLM 回答")

    query = st.text_input("输入问题", key="std_query", placeholder="例如：What is PyTorch?")
    col1, col2 = st.columns([1, 5])
    with col1:
        std_btn = st.button("提问", type="primary", use_container_width=True)
    with col2:
        pass

    if std_btn and query:
        with st.spinner("思考中..."):
            resp = api_post("/query", {"question": query})
        if "error" in resp:
            st.error(resp["error"])
        else:
            st.markdown(resp.get("answer", "无回答"))
            with st.expander("📋 原始响应"):
                show_json(resp)

# =====================
# Tab3: 混合检索
# =====================

with tab3:
    st.subheader("混合检索 + Reranker 精排")
    st.caption("稠密向量 + BM25 + RRF 融合，可选 Cross-Encoder 重排序")

    query_h = st.text_input("输入查询", key="hybrid_query", placeholder="例如：What is Python?")
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        top_k = st.number_input("召回数量", 3, 50, 10)
    with col2:
        use_reranker = st.checkbox("启用 Reranker", value=True)
    with col3:
        hybrid_btn = st.button("检索", type="primary", use_container_width=True)

    if hybrid_btn and query_h:
        with st.spinner("检索中..."):
            resp = api_post("/query/hybrid", {
                "question": query_h,
                "top_k": top_k,
                "use_reranker": use_reranker,
            })
        if "error" in resp:
            st.error(resp["error"])
        else:
            result = resp.get("result", {})

            st.subheader("📊 稠密检索 Top-5")
            for doc in result.get("dense_top", [])[:5]:
                score = doc.get("score", 0)
                color = "🟢" if score > 0 else "🔴"
                st.markdown(f"{color} **{doc['id']}** · 分数 `{score:.4f}`")
                st.caption(doc["text"][:120])
                st.divider()

            st.subheader("📊 混合检索 Top-5（稠密 + BM25 + RRF）")
            for doc in result.get("hybrid_top", [])[:5]:
                st.markdown(f"**{doc['id']}** · RRF `{doc.get('rrf_score', 0):.4f}`")
                st.caption(doc["text"][:120])
                st.divider()

            if use_reranker and "reranked" in result:
                st.subheader("🎯 Reranker 重排序 Top-5（Cross-Encoder）")
                for doc in result["reranked"][:5]:
                    ce = doc.get("ce_score", 0)
                    color = "🟢" if ce > 0 else "🔴"
                    st.markdown(f"{color} **{doc['id']}** · CE 分数 `{ce:.4f}`")
                    st.caption(doc["text"][:120])
                    st.divider()

            with st.expander("📋 原始 JSON"):
                show_json(resp)

# =====================
# Tab4: Multi-Agent
# =====================

with tab4:
    st.subheader("Multi-Agent 写作流水线")
    st.caption("研究员 → 写作者 → 审核员，带持久化记忆和监控追踪")

    topic = st.text_input("输入主题", key="agent_topic",
                          placeholder="例如：Transformer 的自注意力机制")
    col1, col2 = st.columns([1, 2])
    with col1:
        max_retries = st.number_input("最大重试次数", 1, 5, 2)
    with col2:
        agent_btn = st.button("开始写作", type="primary", use_container_width=True)

    if agent_btn and topic:
        with st.spinner(f"正在写《{topic}》..."):
            resp = api_post("/agent/write", {"topic": topic, "max_retries": max_retries})
        if "error" in resp:
            st.error(resp["error"])
        else:
            result = resp.get("result", {})

            status = "✅ 通过" if result.get("passed") else "❌ 未通过"
            st.markdown(f"## {status}")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("评分", f'{result.get("rating", 0)}/5')
            col2.metric("尝试次数", result.get("attempts", 0))
            col3.metric("耗时", f'{result.get("duration_s", 0)}s')
            col4.metric("Trace ID", result.get("trace_id", "")[:8])

            article = result.get("article", "")
            if article:
                st.divider()
                st.subheader("📝 生成文章")
                try:
                    art_json = json.loads(article)
                    st.markdown(f"### {art_json.get('title', '')}")
                    st.write(art_json.get("content", "")[:1000])
                except json.JSONDecodeError:
                    st.write(article[:1000])

            monitor = result.get("monitor", {})
            if monitor:
                st.divider()
                st.subheader("📊 监控追踪")
                metrics = monitor.get("agent_metrics", {})
                for agent, m in metrics.items():
                    st.caption(f"{agent}: {m.get('calls', 0)} 次调用 · "
                               f"平均 {m.get('avg_duration_s', 0)}s · "
                               f"成功率 {m.get('success', 0)}/{m.get('calls', 0)}")

            with st.expander("📋 原始 JSON"):
                show_json(resp)

# =============================================
# 页脚
# =============================================

st.divider()
st.caption("RAGNEXUS · GitHub: github.com/inervers/RAGNEXUS")
