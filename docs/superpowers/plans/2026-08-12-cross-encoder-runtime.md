# Cross-Encoder Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package and load a verified multilingual Cross-Encoder in the standard RAGNEXUS image.

**Architecture:** A pinned manifest downloads only large immutable artifacts; reviewed small configs come from git. `Reranker` resolves an explicit offline path and preserves truthful fallback status.

**Tech Stack:** Python 3.11, SentenceTransformers 2.7.0, Docker, Hugging Face immutable revisions.

## Global Constraints

- Model ID: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`.
- Revision: `1427fd652930e4ba29e8149678df786c240d8825`.
- Runtime must never download a model.
- Do not include ONNX, OpenVINO, or `pytorch_model.bin`.

---

### Task 1: Pin and load the runtime snapshot

**Files:** `models/manifests/cross-encoder-*.json`, `Dockerfile`, `docker-compose.yml`, `rag_advanced.py`, and focused tests.

**Interfaces:** Consumes the existing hash-checking snapshot downloader and produces `RAG_RERANKER_MODEL_SOURCE` plus truthful `Reranker.status()`.

- [x] Add failing tests for the explicit offline path and required image assets.
- [x] Confirm failure because the path and assets are absent.
- [x] Add the pinned manifest/configs, Docker download layer, Compose environment, and offline loader.
- [x] Run focused tests and the offline backend suite.
- [ ] Rebuild `rag-api` and run a Chinese reranking smoke when the model network path is available.
