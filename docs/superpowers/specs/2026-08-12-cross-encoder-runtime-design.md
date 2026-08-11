# Cross-Encoder Runtime Design

## Goal

Make RAGNEXUS execute a real multilingual Cross-Encoder rerank locally instead of falling back because `/app/models/cross-encoder` is absent.

## Decision

Embed the six runtime files for `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` at immutable revision `1427fd652930e4ba29e8149678df786c240d8825` in the standard Docker image. Download only Safetensors and tokenizer assets, verify the three large files by SHA-256 and byte size, and keep three small reviewed JSON configs in git. Do not ship ONNX, OpenVINO, or duplicate pickle weights.

The runtime path is configured through `RAG_RERANKER_MODEL_SOURCE`, defaults to `/opt/models/cross-encoder` in Docker, and is loaded offline. Missing or invalid artifacts remain an explicit `fallback`; successful load reports `mode=cross_encoder`.

## Alternatives Rejected

- Host bind mount: smaller image, but clone and migration remain non-reproducible.
- Remote reranker API: smaller local footprint, but adds network, cost, and credential dependencies.

## Verification

- Unit tests pin the runtime path and image assets.
- Docker build verifies immutable files before committing a layer.
- Container smoke checks `Reranker.status().mode == "cross_encoder"` and Chinese query/passage score ordering.

The first uncached image build requires working access to Hugging Face or `hf-mirror`.
