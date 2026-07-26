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

# === 第③层：下载嵌入模型（镜像加速）===
# 使用 hf-mirror.com 加速，避免被墙
ENV HF_ENDPOINT=https://hf-mirror.com
RUN python -c "\
from transformers import AutoTokenizer, AutoModel;\
name = 'sentence-transformers/all-MiniLM-L6-v2';\
print('Downloading tokenizer...');\
AutoTokenizer.from_pretrained(name, local_files_only=False);\
print('Downloading model...');\
AutoModel.from_pretrained(name, local_files_only=False);\
print('Model cached.')\
"

# === 第④层：代码（变动最频繁）===
COPY rag_api.py rag_advanced.py rag_multiagent.py pdf_parser.py ocr_client.py .
RUN mkdir -p /data/chroma_db /data/logs /app/memory

EXPOSE 8000

CMD ["uvicorn", "rag_api:app", "--host", "0.0.0.0", "--port", "8000"]
