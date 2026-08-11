# RAGNEXUS standard reproducible API image.
# The legacy offline-wheel path is preserved in Dockerfile.legacy.
FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG HF_ENDPOINT=https://hf-mirror.com

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/root/.cache/huggingface \
    HF_HUB_DISABLE_SYMLINKS=1 \
    HF_ENDPOINT=${HF_ENDPOINT} \
    RAG_EMBEDDING_MODEL_SOURCE=/opt/models/multilingual-minilm-l12-v2 \
    RAG_EMBEDDING_MANIFEST=/opt/models/manifests/paraphrase-multilingual-MiniLM-L12-v2.json \
    RAG_EMBEDDING_MODEL_ID=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
    RAG_EMBEDDING_MODEL_REVISION=e8f8c211226b894fcb81acc59f3b34ba3efd5f42 \
    RAG_EMBEDDING_POOLING=masked_mean

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt .
RUN python -m pip install --no-cache-dir --index-url "${TORCH_INDEX_URL}" torch==2.5.1 \
    && python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements-api.txt

# Download and hash-check immutable V2 and rollback snapshots. Runtime remains
# offline/local-only; manifests are the single source of model provenance.
COPY scripts/download_embedding_snapshot.py /tmp/download_embedding_snapshot.py
COPY models/manifests/all-MiniLM-L6-v2.json /opt/models/manifests/all-MiniLM-L6-v2.json
COPY models/manifests/paraphrase-multilingual-MiniLM-L12-v2.json /opt/models/manifests/paraphrase-multilingual-MiniLM-L12-v2.json
RUN python /tmp/download_embedding_snapshot.py \
      --endpoint "${HF_ENDPOINT}" \
      --manifest /opt/models/manifests/paraphrase-multilingual-MiniLM-L12-v2.json \
      --output /opt/models/multilingual-minilm-l12-v2 \
    && python /tmp/download_embedding_snapshot.py \
      --endpoint "${HF_ENDPOINT}" \
      --manifest /opt/models/manifests/all-MiniLM-L6-v2.json \
      --output /opt/models/legacy-minilm-l6-v2 \
    && rm /tmp/download_embedding_snapshot.py

COPY rag_api.py rag_advanced.py rag_multiagent.py retrieval_service.py security_config.py document_ingest.py embedding_runtime.py runtime_bootstrap.py agent_contract.py request_limits.py pdf_parser.py ocr_client.py materialize_kb_v2.py ./
COPY kb_v2/build /app/kb_v2/build

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=6 \
    CMD python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); assert data['status']=='ok'"

CMD ["uvicorn", "rag_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
