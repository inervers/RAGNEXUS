#!/usr/bin/env python3
"""Materialize a verified V2 corpus into a new empty Chroma directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from embedding_runtime import VerifiedEmbedding


class MaterializationError(RuntimeError):
    """Raised before an unsafe or unverifiable materialization step."""


def validate_target(target: str | Path, protected_paths: Iterable[str | Path]) -> Path:
    resolved = Path(target).resolve()
    protected = {Path(path).resolve() for path in protected_paths}
    if any(resolved == path or path in resolved.parents for path in protected):
        raise MaterializationError(f"target is a protected V1 path: {resolved}")
    if resolved.exists():
        if not resolved.is_dir():
            raise MaterializationError(f"target exists and is not a directory: {resolved}")
        if any(resolved.iterdir()):
            raise MaterializationError(f"target directory is non-empty: {resolved}")
    return resolved


def load_verified_corpus(artifact_dir: str | Path) -> tuple[dict[str, Any], ...]:
    root = Path(artifact_dir)
    corpus_path = root / "corpus.jsonl"
    manifest_path = root / "manifest.json"
    try:
        corpus_bytes = corpus_path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"cannot read corpus artifact: {exc}") from exc
    actual_hash = hashlib.sha256(corpus_bytes).hexdigest()
    if manifest.get("corpus_sha256") != actual_hash:
        raise MaterializationError(
            f"corpus SHA256 mismatch: manifest={manifest.get('corpus_sha256')} actual={actual_hash}"
        )

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(corpus_bytes.decode("utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            item = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise MaterializationError(f"invalid JSONL at line {line_number}: {exc}") from exc
        chunk_id = item.get("id")
        metadata = item.get("metadata")
        if not isinstance(chunk_id, str) or not isinstance(item.get("document"), str) or not isinstance(metadata, dict):
            raise MaterializationError(f"invalid corpus record at line {line_number}")
        if chunk_id in seen:
            raise MaterializationError(f"duplicate chunk ID: {chunk_id}")
        if metadata.get("chunk_id") != chunk_id:
            raise MaterializationError(f"record/metadata chunk ID mismatch: {chunk_id}")
        if metadata.get("status") != "current" or metadata.get("sensitivity") != "public":
            raise MaterializationError(f"record is not public/current: {chunk_id}")
        seen.add(chunk_id)
        records.append(item)
    if manifest.get("chunk_count") != len(records):
        raise MaterializationError(
            f"chunk count mismatch: manifest={manifest.get('chunk_count')} actual={len(records)}"
        )
    return tuple(records)


def materialize_records(
    records: Iterable[dict[str, Any]],
    collection: Any,
    *,
    batch_size: int = 64,
) -> dict[str, int]:
    if batch_size <= 0:
        raise MaterializationError("batch_size must be positive")
    if collection.count() != 0:
        raise MaterializationError("collection is not empty")
    materialized = list(records)
    expected_ids = [item["id"] for item in materialized]
    if len(expected_ids) != len(set(expected_ids)):
        raise MaterializationError("duplicate chunk IDs in materialization input")
    for start in range(0, len(materialized), batch_size):
        batch = materialized[start : start + batch_size]
        collection.add(
            ids=[item["id"] for item in batch],
            documents=[item["document"] for item in batch],
            metadatas=[item["metadata"] for item in batch],
        )
    actual_ids = collection.get()["ids"]
    if collection.count() != len(expected_ids) or set(actual_ids) != set(expected_ids):
        raise MaterializationError(
            f"post-write verification failed: expected={len(expected_ids)} actual={collection.count()}"
        )
    return {"chunks": len(expected_ids), "verified_ids": len(actual_ids)}


def create_verified_collection(client: Any, name: str, embedding: Any) -> Any:
    provenance = embedding.provenance()
    collection = client.get_or_create_collection(
        name=name,
        embedding_function=embedding,
        metadata=provenance,
    )
    if collection.metadata != provenance:
        raise MaterializationError(
            f"collection provenance mismatch: expected={provenance} "
            f"actual={collection.metadata}"
        )
    return collection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", default="kb_v2/build")
    parser.add_argument("--target", default="chroma_db_v2_candidate")
    parser.add_argument(
        "--protected",
        action="append",
        default=["chroma_db", "chroma_db_v2"],
    )
    parser.add_argument("--collection", default="rag_knowledge")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--model-dir",
        default=".rag06-models/multilingual-minilm-l12-v2",
    )
    parser.add_argument(
        "--model-manifest",
        default="models/manifests/paraphrase-multilingual-MiniLM-L12-v2.json",
    )
    parser.add_argument("--check-only", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    target = validate_target(args.target, args.protected)
    records = load_verified_corpus(args.artifact)
    if args.check_only:
        print(f"validated_chunks={len(records)}")
        print(f"safe_target={target}")
        return

    embedding = VerifiedEmbedding(args.model_dir, args.model_manifest)
    target.mkdir(parents=True, exist_ok=True)
    import chromadb

    client = chromadb.PersistentClient(
        path=str(target),
        settings=chromadb.config.Settings(anonymized_telemetry=False),
    )
    collection = create_verified_collection(client, args.collection, embedding)
    result = materialize_records(records, collection, batch_size=args.batch_size)
    print(f"target={target}")
    print(f"collection={args.collection}")
    print(f"chunks={result['chunks']}")
    print(f"verified_ids={result['verified_ids']}")


if __name__ == "__main__":
    main()
