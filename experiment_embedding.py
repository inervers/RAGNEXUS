"""Compatibility exports for the verified embedding used by RAG-06."""

from embedding_runtime import (
    ModelSpec,
    VerifiedEmbedding,
    masked_mean_pool,
    verify_snapshot,
)

# Keep the public experiment name stable while production and experiments share
# one implementation and therefore one vector-space/provenance contract.
ExperimentEmbedding = VerifiedEmbedding

__all__ = (
    "ExperimentEmbedding",
    "ModelSpec",
    "masked_mean_pool",
    "verify_snapshot",
)
