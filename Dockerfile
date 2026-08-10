# RAGNEXUS standard reproducible API image.
# The legacy offline-wheel path is preserved in Dockerfile.legacy.
FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG HF_ENDPOINT=https://hf-mirror.com
ARG RAG_EMBEDDING_MODEL_REPO=sentence-transformers/all-MiniLM-L6-v2
ARG RAG_EMBEDDING_MODEL_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/root/.cache/huggingface \
    HF_HUB_DISABLE_SYMLINKS=1 \
    HF_ENDPOINT=${HF_ENDPOINT} \
    RAG_EMBEDDING_MODEL_ID=/opt/models/all-MiniLM-L6-v2 \
    RAG_EMBEDDING_MODEL_REVISION=${RAG_EMBEDDING_MODEL_REVISION}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt .
RUN python -m pip install --no-cache-dir --index-url "${TORCH_INDEX_URL}" torch==2.5.1 \
    && python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements-api.txt

# Download and hash-check one immutable snapshot. Runtime remains offline/local-only.
COPY scripts/download_embedding_snapshot.py /tmp/download_embedding_snapshot.py
RUN python /tmp/download_embedding_snapshot.py \
      --endpoint "${HF_ENDPOINT}" \
      --repo "${RAG_EMBEDDING_MODEL_REPO}" \
      --revision "${RAG_EMBEDDING_MODEL_REVISION}" \
      --output /opt/models/all-MiniLM-L6-v2 \
    && rm /tmp/download_embedding_snapshot.py

COPY rag_api.py rag_advanced.py rag_multiagent.py retrieval_service.py security_config.py document_ingest.py embedding_runtime.py agent_contract.py pdf_parser.py ocr_client.py ./

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=6 \
    CMD python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); assert data['status']=='ok'"

CMD ["uvicorn", "rag_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
