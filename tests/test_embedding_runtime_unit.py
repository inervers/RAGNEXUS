import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from embedding_runtime import (
    ModelSpec,
    PoolingConfigurationError,
    VerifiedEmbedding,
    embedding_function_name,
    embed_batch,
    resolve_embedding_runtime_config,
    resolve_pooling_mode,
    validate_collection_provenance,
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


def test_model_spec_builds_complete_embedding_provenance() -> None:
    spec = ModelSpec(
        model_id="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        revision="e8f8c211",
        pooling="masked_mean",
    )

    assert spec.provenance("a" * 64) == {
        "embedding_model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "embedding_model_revision": "e8f8c211",
        "embedding_pooling": "masked_mean",
        "embedding_snapshot_sha256": "a" * 64,
    }


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("embedding_model_id", "sentence-transformers/wrong"),
        ("embedding_model_revision", "wrong-revision"),
        ("embedding_pooling", "legacy_mean"),
        ("embedding_snapshot_sha256", "0" * 64),
    ],
)
def test_nonempty_collection_rejects_any_embedding_provenance_drift(
    field: str, wrong_value: str
) -> None:
    expected = {
        "embedding_model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "embedding_model_revision": "e8f8c211",
        "embedding_pooling": "masked_mean",
        "embedding_snapshot_sha256": "a" * 64,
    }
    stored = dict(expected)
    stored[field] = wrong_value

    with pytest.raises(PoolingConfigurationError, match=field):
        validate_collection_provenance(expected, count=184, metadata=stored)


def test_legacy_collection_without_provenance_only_accepts_legacy_runtime() -> None:
    legacy = {
        "embedding_model_id": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_model_revision": "1110a243",
        "embedding_pooling": "legacy_mean",
        "embedding_snapshot_sha256": "b" * 64,
    }
    validate_collection_provenance(legacy, count=166, metadata=None)

    masked = dict(legacy, embedding_pooling="masked_mean")
    with pytest.raises(PoolingConfigurationError, match="re-embed"):
        validate_collection_provenance(masked, count=166, metadata=None)


def test_verified_embedding_exposes_complete_provenance_without_loading_model() -> None:
    embedding = object.__new__(VerifiedEmbedding)
    embedding.spec = ModelSpec(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "e8f8c211",
        "masked_mean",
    )
    embedding.snapshot_sha256 = "c" * 64

    assert embedding.provenance()["embedding_snapshot_sha256"] == "c" * 64
    assert "multilingual" in embedding.name()


def test_runtime_config_defaults_to_tracked_multilingual_manifest(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "models/manifests/paraphrase-multilingual-MiniLM-L12-v2.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                "revision": "e8f8c211",
                "pooling": "masked_mean",
                "files": [{"path": "config.json", "size": 1, "sha256": "a" * 64}],
            }
        ),
        encoding="utf-8",
    )

    config = resolve_embedding_runtime_config({}, tmp_path)

    assert config.snapshot_dir == (
        tmp_path / ".rag06-models/multilingual-minilm-l12-v2"
    ).resolve()
    assert config.manifest_path == manifest.resolve()
    assert config.spec.pooling == "masked_mean"


def test_runtime_config_rejects_environment_drift_from_manifest(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "model_id": "sentence-transformers/example",
                "revision": "frozen-revision",
                "pooling": "masked_mean",
                "files": [{"path": "config.json", "size": 1, "sha256": "a" * 64}],
            }
        ),
        encoding="utf-8",
    )
    env = {
        "RAG_EMBEDDING_MODEL_SOURCE": str(snapshot),
        "RAG_EMBEDDING_MANIFEST": str(manifest),
        "RAG_EMBEDDING_MODEL_REVISION": "different-revision",
    }

    with pytest.raises(ValueError, match="RAG_EMBEDDING_MODEL_REVISION"):
        resolve_embedding_runtime_config(env, tmp_path)
