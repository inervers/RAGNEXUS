from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from experiment_embedding import (
    ExperimentEmbedding,
    ModelSpec,
    masked_mean_pool,
    verify_snapshot,
)


def test_model_spec_makes_pooling_and_model_identity_explicit() -> None:
    spec = ModelSpec(
        model_id="sentence-transformers/example",
        revision="abc123",
        pooling="legacy_mean",
    )

    assert spec.to_dict() == {
        "model_id": "sentence-transformers/example",
        "revision": "abc123",
        "pooling": "legacy_mean",
    }


def test_model_spec_rejects_unknown_pooling() -> None:
    with pytest.raises(ValueError, match="pooling"):
        ModelSpec("sentence-transformers/example", "abc123", "cls")


def test_verify_snapshot_checks_each_file_and_returns_stable_aggregate(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "config.json").write_bytes(b"config")
    (snapshot / "model.safetensors").write_bytes(b"weights")
    files = []
    for filename in ("config.json", "model.safetensors"):
        data = (snapshot / filename).read_bytes()
        files.append(
            {
                "path": filename,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": files}), encoding="utf-8")

    first = verify_snapshot(snapshot, manifest)
    second = verify_snapshot(snapshot, manifest)

    assert first == second
    assert len(first) == 64


def test_verify_snapshot_rejects_tampering(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "config.json").write_bytes(b"tampered")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "config.json",
                        "size": 6,
                        "sha256": hashlib.sha256(b"config").hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mismatch"):
        verify_snapshot(snapshot, manifest)


def test_masked_mean_pool_excludes_padding_tokens() -> None:
    torch = pytest.importorskip("torch")
    hidden = torch.tensor([[[2.0, 4.0], [6.0, 8.0], [100.0, 100.0]]])
    mask = torch.tensor([[1, 1, 0]])

    pooled = masked_mean_pool(hidden, mask)

    assert pooled.tolist() == [[4.0, 6.0]]


def test_embedding_provenance_includes_pooling_and_verified_snapshot() -> None:
    spec = ModelSpec("sentence-transformers/example", "abc123", "masked_mean")
    embedding = object.__new__(ExperimentEmbedding)
    embedding.spec = spec
    embedding.snapshot_sha256 = "f" * 64

    assert embedding.provenance() == {
        "embedding_model_id": "sentence-transformers/example",
        "embedding_model_revision": "abc123",
        "embedding_pooling": "masked_mean",
        "embedding_snapshot_sha256": "f" * 64,
    }


def test_embedding_exposes_chroma_query_contract() -> None:
    embedding = object.__new__(ExperimentEmbedding)
    embedding._embed = lambda texts: FakeVectors([[0.1, 0.2]])

    assert embedding.embed_query(["query"]) == [[0.1, 0.2]]


class FakeVectors:
    def __init__(self, values: list[list[float]]) -> None:
        self.values = values

    def __iter__(self):
        return iter(FakeVector(value) for value in self.values)


class FakeVector:
    def __init__(self, value: list[float]) -> None:
        self.value = value

    def tolist(self) -> list[float]:
        return self.value
