from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from materialize_kb_v2 import (
    MaterializationError,
    load_verified_corpus,
    materialize_records,
    validate_target,
)


def record(chunk_id: str = "doc:v1#0123456789abcdef") -> dict:
    return {
        "id": chunk_id,
        "document": "# Fixture\n\n## Section\n\n可信事实。",
        "metadata": {
            "chunk_id": chunk_id,
            "doc_id": "doc:v1",
            "status": "current",
            "sensitivity": "public",
            "project": "ragnexus",
        },
    }


def write_artifacts(root: Path, records: list[dict]) -> Path:
    root.mkdir()
    corpus = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for item in records)
    corpus_bytes = corpus.encode("utf-8")
    (root / "corpus.jsonl").write_bytes(corpus_bytes)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
                "chunk_count": len(records),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


def test_validate_target_rejects_protected_resolved_path(tmp_path: Path) -> None:
    protected = tmp_path / "chroma_db"
    protected.mkdir()
    aliased = protected.parent / "." / protected.name

    with pytest.raises(MaterializationError, match="protected"):
        validate_target(aliased, [protected])


def test_validate_target_rejects_descendant_of_protected_path(tmp_path: Path) -> None:
    protected = tmp_path / "chroma_db"
    protected.mkdir()

    with pytest.raises(MaterializationError, match="protected"):
        validate_target(protected / "nested-v2", [protected])


def test_validate_target_rejects_non_empty_directory(tmp_path: Path) -> None:
    target = tmp_path / "chroma_db_v2"
    target.mkdir()
    (target / "existing.bin").write_bytes(b"data")

    with pytest.raises(MaterializationError, match="non-empty"):
        validate_target(target, [tmp_path / "chroma_db"])


def test_validate_target_accepts_missing_or_empty_unprotected_path(tmp_path: Path) -> None:
    missing = tmp_path / "chroma_db_v2"
    empty = tmp_path / "chroma_db_v3"
    empty.mkdir()

    assert validate_target(missing, [tmp_path / "chroma_db"]) == missing.resolve()
    assert validate_target(empty, [tmp_path / "chroma_db"]) == empty.resolve()


def test_load_verified_corpus_rejects_manifest_hash_mismatch(tmp_path: Path) -> None:
    artifacts = write_artifacts(tmp_path / "build", [record()])
    (artifacts / "corpus.jsonl").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(MaterializationError, match="SHA256"):
        load_verified_corpus(artifacts)


def test_load_verified_corpus_rejects_duplicate_or_inconsistent_ids(tmp_path: Path) -> None:
    duplicated = [record(), record()]
    artifacts = write_artifacts(tmp_path / "build", duplicated)

    with pytest.raises(MaterializationError, match="duplicate"):
        load_verified_corpus(artifacts)


class FakeCollection:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, dict]] = {}

    def count(self) -> int:
        return len(self.records)

    def add(self, *, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        for chunk_id, document, metadata in zip(ids, documents, metadatas):
            self.records[chunk_id] = (document, metadata)

    def get(self) -> dict:
        return {"ids": list(self.records)}


def test_materialize_records_writes_batches_and_verifies_exact_ids() -> None:
    records = [record("doc:v1#0123456789abcdef"), record("doc:v1#fedcba9876543210")]
    collection = FakeCollection()

    result = materialize_records(records, collection, batch_size=1)

    assert result == {"chunks": 2, "verified_ids": 2}
    assert set(collection.records) == {item["id"] for item in records}
    assert collection.records[records[0]["id"]][1]["chunk_id"] == records[0]["id"]


def test_materialize_records_refuses_non_empty_collection() -> None:
    collection = FakeCollection()
    collection.records["existing"] = ("old", {})

    with pytest.raises(MaterializationError, match="collection is not empty"):
        materialize_records([record()], collection)
