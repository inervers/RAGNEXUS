"""Padding-safe embedding helpers with no model-loading side effects."""

from __future__ import annotations


def masked_mean_pool(last_hidden_state, attention_mask):
    expanded_mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    token_sum = (last_hidden_state * expanded_mask).sum(dim=1)
    token_count = expanded_mask.sum(dim=1).clamp(min=1e-9)
    return token_sum / token_count


def embed_batch(texts, tokenizer, model, torch_module, max_length: int = 256):
    inputs = tokenizer(
        texts,
        truncation=True,
        padding=True,
        return_tensors="pt",
        max_length=max_length,
    )
    with torch_module.no_grad():
        hidden = model(**inputs).last_hidden_state
        pooled = masked_mean_pool(hidden, inputs["attention_mask"])
        normalized = torch_module.nn.functional.normalize(pooled, p=2, dim=1)
    return normalized.cpu().numpy()
