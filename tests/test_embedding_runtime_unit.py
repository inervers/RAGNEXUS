from types import SimpleNamespace

import numpy as np
import pytest

from embedding_runtime import (
    PoolingConfigurationError,
    embedding_function_name,
    embed_batch,
    resolve_pooling_mode,
    validate_collection_pooling,
)


class FakeTokenizer:
    def __call__(self, texts, **kwargs):
        torch = pytest.importorskip("torch")
        token_ids = {
            "short": [1, 2],
            "long": [3, 4, 5],
        }
        longest = max(len(token_ids[text]) for text in texts)
        ids = []
        masks = []
        for text in texts:
            values = token_ids[text]
            padding = longest - len(values)
            ids.append(values + [0] * padding)
            masks.append([1] * len(values) + [0] * padding)
        return {
            "input_ids": torch.tensor(ids),
            "attention_mask": torch.tensor(masks),
        }


class FakeModel:
    def __call__(self, input_ids, attention_mask):
        torch = pytest.importorskip("torch")
        vectors = {
            0: [100.0, 100.0],
            1: [2.0, 0.0],
            2: [0.0, 2.0],
            3: [1.0, 2.0],
            4: [2.0, 3.0],
            5: [3.0, 4.0],
        }
        hidden = torch.tensor(
            [[vectors[int(token)] for token in row] for row in input_ids]
        )
        return SimpleNamespace(last_hidden_state=hidden)


def test_short_embedding_is_independent_of_padding_batch_companions() -> None:
    torch = pytest.importorskip("torch")
    tokenizer = FakeTokenizer()
    model = FakeModel()

    single = embed_batch(["short"], tokenizer, model, torch)[0]
    batched = embed_batch(["short", "long"], tokenizer, model, torch)[0]

    assert np.allclose(single, batched, atol=1e-6)
    assert np.isclose(np.dot(single, batched), 1.0, atol=1e-6)


def test_existing_unversioned_collection_defaults_to_legacy_pooling() -> None:
    assert resolve_pooling_mode(None) == "legacy_mean"
    validate_collection_pooling("legacy_mean", count=166, metadata=None)


def test_masked_pooling_rejects_nonempty_collection_without_matching_provenance() -> None:
    with pytest.raises(PoolingConfigurationError, match="re-embed"):
        validate_collection_pooling("masked_mean", count=166, metadata=None)

    with pytest.raises(PoolingConfigurationError, match="legacy_mean"):
        validate_collection_pooling(
            "masked_mean", count=166, metadata={"embedding_pooling": "legacy_mean"}
        )


def test_pooling_mode_rejects_unknown_value() -> None:
    with pytest.raises(PoolingConfigurationError, match="RAG_EMBEDDING_POOLING"):
        resolve_pooling_mode("mean")


def test_legacy_embedding_name_stays_backward_compatible() -> None:
    assert embedding_function_name("legacy_mean") == "MiniLM-L6-v2-mean-pooling"
    assert embedding_function_name("masked_mean") == "MiniLM-L6-v2-masked_mean-v1"
