# ============================================================
# RAGNEXUS rag-api 镜像（增量构建）
# 基础：旧镜像 ragnxus-rag-api:0.5.17-backup
#   （torch 2.5.1 + chromadb 0.5.17 + 应用依赖已装）
# 增量1：离线升级 chromadb 0.5.17 → 1.5.9（.wheels 本地交叉下载）
# 增量2：覆盖最新代码（MiniLMEmbedding 已适配 chromadb 1.x）
# 背景 2026-08-02：WSL2 出口对 pypi 限速/SSL EOF、清华源 403 风控、
#   torch 2.5.1 与本地 Python 3.13 不兼容 → 旧镜像增量升级绕开大下载
# ============================================================
FROM ragnxus-rag-api:0.5.17-backup

# === 增量层1：chromadb 0.5.17 → 1.5.9（离线 wheel，不碰网络）===
COPY .wheels /wheels
RUN pip install --no-index --find-links=/wheels chromadb==1.5.9 && rm -rf /wheels

# === 增量层2：最新代码（覆盖旧镜像中的旧版）===
COPY rag_api.py rag_advanced.py rag_multiagent.py pdf_parser.py ocr_client.py .

# 旧镜像已含：WORKDIR=/app、EXPOSE 8000、CMD uvicorn、第②层依赖、HF 缓存
