FROM python:3.11-slim

WORKDIR /app

# === 第①层：核心依赖（chromadb、torch、sentence-transformers）===
# 这些几乎不动，装好后缓存基本不失效
COPY requirements-base.txt .
RUN pip install --no-cache-dir -r requirements-base.txt

# === 第②层：应用依赖（FastAPI、streamlit、openai）===
# 加新接口时可能变动，但重装快（不含 torch 那 3.5GB）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# === 第③层：代码（变动最频繁）===
COPY rag_api.py rag_advanced.py rag_multiagent.py pdf_parser.py .
RUN mkdir -p /data/chroma_db /data/logs /app/memory

EXPOSE 8000

CMD ["uvicorn", "rag_api:app", "--host", "0.0.0.0", "--port", "8000"]
