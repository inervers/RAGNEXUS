"""V2 evaluation-set contract and held-out access guard."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


CATEGORY_COUNTS = {
    "exact": 10,
    "semantic": 8,
    "troubleshooting": 8,
    "multidoc": 6,
    "version_conflict": 4,
    "unanswerable": 4,
}
SPLIT_COUNTS = {"development": 24, "heldout": 16}
DIFFICULTIES = {"easy", "medium", "hard"}
QUESTION_FIELDS = {
    "id",
    "category",
    "split",
    "difficulty",
    "question",
    "should_abstain",
    "relevant_doc_ids",
    "relevant_chunk_ids",
    "answer_key_points",
    "reference_answer",
    "source_versions",
}


def _non_empty_strings(value, field, question_id, *, allow_empty=False):
    if not isinstance(value, list):
        raise ValueError(f"{question_id}.{field} must be a list")
    if not allow_empty and not value:
        raise ValueError(f"{question_id}: positive ground truth requires {field}")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{question_id}.{field} must contain non-empty strings")


def _manifest_index(manifest):
    documents = manifest.get("documents") if isinstance(manifest, dict) else None
    if not isinstance(documents, list):
        raise ValueError("manifest.documents must be a list")
    doc_ids = set()
    source_versions = {}
    chunk_to_doc = {}
    for document in documents:
        doc_id = document.get("doc_id") if isinstance(document, dict) else None
        chunk_ids = document.get("chunk_ids") if isinstance(document, dict) else None
        if not isinstance(doc_id, str) or not doc_id or not isinstance(chunk_ids, list):
            raise ValueError("manifest document contract is invalid")
        commit = document.get("commit")
        if not isinstance(commit, str) or not commit:
            raise ValueError(f"manifest document {doc_id} has no commit")
        doc_ids.add(doc_id)
        source_versions[doc_id] = f"{doc_id}@{commit}"
        for chunk_id in chunk_ids:
            if chunk_id in chunk_to_doc:
                raise ValueError(f"manifest has duplicate chunk ID: {chunk_id}")
            chunk_to_doc[chunk_id] = doc_id
    return doc_ids, chunk_to_doc, source_versions


def validate_eval_set(dataset, manifest):
    """Validate the frozen V2 contract and every ground-truth reference."""
    if not isinstance(dataset, dict) or set(dataset) != {"meta", "questions"}:
        raise ValueError("eval set must contain exactly meta and questions")
    meta = dataset["meta"]
    questions = dataset["questions"]
    if not isinstance(meta, dict) or meta.get("schema_version") != 2:
        raise ValueError("meta.schema_version must be 2")
    manifest_sha = meta.get("corpus_manifest_sha256")
    if not isinstance(manifest_sha, str) or len(manifest_sha) != 64:
        raise ValueError("meta.corpus_manifest_sha256 must be a SHA256 hex string")
    if not isinstance(questions, list) or len(questions) != 40:
        raise ValueError("V2 evaluation set must contain exactly 40 questions")

    ids = [item.get("id") for item in questions if isinstance(item, dict)]
    if len(ids) != 40 or any(not isinstance(item_id, str) or not item_id for item_id in ids):
        raise ValueError("every question needs a non-empty id")
    if len(set(ids)) != len(ids):
        raise ValueError("question IDs must be unique")

    category_counts = Counter(item.get("category") for item in questions)
    if dict(category_counts) != CATEGORY_COUNTS:
        raise ValueError(f"category counts must equal {CATEGORY_COUNTS}")
    split_counts = Counter(item.get("split") for item in questions)
    if dict(split_counts) != SPLIT_COUNTS:
        raise ValueError(f"split counts must equal {SPLIT_COUNTS}")

    doc_ids, chunk_to_doc, source_versions = _manifest_index(manifest)
    for item in questions:
        question_id = item["id"]
        if set(item) != QUESTION_FIELDS:
            raise ValueError(f"{question_id} fields do not match the V2 contract")
        if item["difficulty"] not in DIFFICULTIES:
            raise ValueError(f"{question_id}.difficulty is invalid")
        if not isinstance(item["question"], str) or not item["question"].strip():
            raise ValueError(f"{question_id}.question must be non-empty")
        if not isinstance(item["should_abstain"], bool):
            raise ValueError(f"{question_id}.should_abstain must be boolean")

        list_fields = (
            "relevant_doc_ids",
            "relevant_chunk_ids",
            "answer_key_points",
            "source_versions",
        )
        if item["category"] == "unanswerable":
            if not item["should_abstain"] or any(item[field] for field in list_fields) or item["reference_answer"]:
                raise ValueError(f"{question_id}: unanswerable ground truth must be empty")
            for field in list_fields:
                _non_empty_strings(item[field], field, question_id, allow_empty=True)
            if not isinstance(item["reference_answer"], str):
                raise ValueError(f"{question_id}.reference_answer must be a string")
            continue

        if item["should_abstain"]:
            raise ValueError(f"{question_id}: positive ground truth cannot abstain")
        for field in list_fields:
            _non_empty_strings(item[field], field, question_id)
        if not isinstance(item["reference_answer"], str) or not item["reference_answer"].strip():
            raise ValueError(f"{question_id}: positive ground truth requires reference_answer")
        for chunk_id in item["relevant_chunk_ids"]:
            if chunk_id not in chunk_to_doc:
                raise ValueError(f"{question_id}: unknown chunk {chunk_id}")
            if chunk_to_doc[chunk_id] not in item["relevant_doc_ids"]:
                raise ValueError(f"{question_id}: doc/chunk mismatch for {chunk_id}")
        if any(doc_id not in doc_ids for doc_id in item["relevant_doc_ids"]):
            raise ValueError(f"{question_id}: unknown relevant document")
        expected_versions = {source_versions[doc_id] for doc_id in item["relevant_doc_ids"]}
        if set(item["source_versions"]) != expected_versions:
            raise ValueError(
                f"{question_id}: source_versions mismatch; expected {sorted(expected_versions)}"
            )
    return dataset


def load_and_validate_eval_set(eval_path, manifest_path):
    eval_path = Path(eval_path)
    manifest_path = Path(manifest_path)
    dataset = json.loads(eval_path.read_text(encoding="utf-8"))
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    actual_sha = hashlib.sha256(manifest_bytes).hexdigest()
    expected_sha = dataset.get("meta", {}).get("corpus_manifest_sha256")
    if expected_sha != actual_sha:
        raise ValueError(
            f"manifest SHA256 mismatch: eval={expected_sha!r}, actual={actual_sha}"
        )
    return validate_eval_set(dataset, manifest)


def select_questions(dataset, split="development", allow_heldout=False):
    if split not in {"development", "heldout", "all"}:
        raise ValueError(f"unknown split: {split}")
    if split in {"heldout", "all"} and not allow_heldout:
        raise ValueError(f"split={split} requires explicit --allow-heldout")
    questions = dataset["questions"]
    if split == "all":
        return list(questions)
    return [item for item in questions if item["split"] == split]
