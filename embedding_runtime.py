"""Padding-safe embedding helpers with no model-loading side effects."""

from __future__ import annotations

POOLING_MODES = {"legacy_mean", "masked_mean"}


class PoolingConfigurationError(ValueError):
    pass


def resolve_pooling_mode(raw_value: str | None) -> str:
    mode = (raw_value or "legacy_mean").strip().lower()
    if mode not in POOLING_MODES:
        raise PoolingConfigurationError(
            f"RAG_EMBEDDING_POOLING must be one of {sorted(POOLING_MODES)}"
        )
    return mode


def embedding_function_name(mode: str) -> str:
    mode = resolve_pooling_mode(mode)
    if mode == "legacy_mean":
        return "MiniLM-L6-v2-mean-pooling"
    return "MiniLM-L6-v2-masked_mean-v1"


def validate_collection_pooling(
    mode: str, count: int, metadata: dict | None
) -> None:
    stored_mode = (metadata or {}).get("embedding_pooling")
    if count == 0:
        return
    if stored_mode is None and mode == "legacy_mean":
        return
    if stored_mode != mode:
        actual = stored_mode or "unknown legacy_mean"
        raise PoolingConfigurationError(
            f"collection embedding_pooling={actual}, runtime={mode}; "
            "re-embed into a new collection before switching"
        )


def masked_mean_pool(last_hidden_state, attention_mask):
    expanded_mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size())
    expanded_mask = expanded_mask.to(
        device=last_hidden_state.device, dtype=last_hidden_state.dtype
    )
    token_sum = (last_hidden_state * expanded_mask).sum(dim=1)
    token_count = expanded_mask.sum(dim=1).clamp(min=1e-9)
    return token_sum / token_count


def embed_batch(
    texts,
    tokenizer,
    model,
    torch_module,
    max_length: int = 256,
    pooling: str = "masked_mean",
):
    pooling = resolve_pooling_mode(pooling)
    inputs = tokenizer(
        texts,
        truncation=True,
        padding=True,
        return_tensors="pt",
        max_length=max_length,
    )
    with torch_module.no_grad():
        hidden = model(**inputs).last_hidden_state
        pooled = (
            hidden.mean(dim=1)
            if pooling == "legacy_mean"
            else masked_mean_pool(hidden, inputs["attention_mask"])
        )
        normalized = torch_module.nn.functional.normalize(pooled, p=2, dim=1)
    return normalized.cpu().numpy()
