#!/usr/bin/env python3
"""Run isolated RAG-06 retrieval experiments or freeze a development result."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from eval_dataset import load_and_validate_eval_set, select_questions
from eval_rag import score_retrieval_result
from experiment_embedding import ExperimentEmbedding, ModelSpec
from materialize_kb_v2 import load_verified_corpus, materialize_records
from rag_advanced import HybridSearch, build_corpus_records
from retrieval_experiment import (
    ExperimentConfig,
    aggregate_by_config,
    choose_best_config,
    freeze_development_result,
    sha256_file,
    validate_heldout_gate,
    write_new_result,
)
from retrieval_service import RetrievalConfig, RetrievalService


DEFAULT_CONFIGS = (
    ExperimentConfig("dense", "dense", 10, 1.0, 1.0),
    ExperimentConfig("hybrid-1-1", "hybrid", 10, 1.0, 1.0),
    ExperimentConfig("hybrid-1-2", "hybrid", 10, 1.0, 2.0),
    ExperimentConfig("hybrid-1-3", "hybrid", 10, 1.0, 3.0),
)


def load_model_spec(manifest_path: str | Path) -> ModelSpec:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return ModelSpec(
        model_id=manifest["model_id"],
        revision=manifest["revision"],
        pooling=manifest["pooling"],
    )


def build_provenance(
    *,
    code_commit: str,
    corpus_path: str | Path,
    manifest_path: str | Path,
    eval_set_path: str | Path,
    embedding: ExperimentEmbedding,
) -> dict:
    return {
        "code_commit": code_commit,
        "corpus_sha256": sha256_file(corpus_path),
        "manifest_sha256": sha256_file(manifest_path),
        "eval_set_sha256": sha256_file(eval_set_path),
        **embedding.provenance(),
    }


def _make_service(records: tuple[dict, ...], embedding: ExperimentEmbedding):
    import chromadb

    client = chromadb.EphemeralClient(
        settings=chromadb.config.Settings(anonymized_telemetry=False)
    )
    collection = client.create_collection(
        name="rag06_experiment",
        embedding_function=embedding,
    )
    materialize_records(records, collection, batch_size=32)
    stored = collection.get(include=["documents"])
    corpus = build_corpus_records(stored.get("ids", []), stored.get("documents", []))
    search = HybridSearch(collection, embedding._embed, corpus)
    service = RetrievalService(
        search_provider=lambda: search,
        corpus_version_provider=lambda: len(records),
    )
    return client, service


def _evaluate(
    items: list[dict],
    configs: tuple[ExperimentConfig, ...],
    service: RetrievalService,
) -> list[dict]:
    rows = []
    for item in items:
        for config in configs:
            started = time.perf_counter()
            try:
                result = service.retrieve(
                    item["question"],
                    RetrievalConfig(
                        strategy=config.strategy,
                        top_k=config.top_k,
                        dense_weight=config.dense_weight,
                        sparse_weight=config.sparse_weight,
                    ),
                    trace_id=f"rag06-{item['id']}-{config.name}",
                )
                selected = result["selected"]
                outcome = score_retrieval_result(
                    selected, item.get("relevant_chunk_ids")
                )
                outcome["selected_ids"] = [entry["id"] for entry in selected]
            except Exception as exc:
                outcome = {"status": "error", "reason": str(exc)[:300]}
            rows.append(
                {
                    "question_id": item["id"],
                    "question": item["question"],
                    "category": item["category"],
                    "difficulty": item["difficulty"],
                    "should_abstain": item["should_abstain"],
                    "relevant_chunk_ids": item.get("relevant_chunk_ids", []),
                    "config": config.name,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "outcome": outcome,
                }
            )
    return rows


def run_experiment(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest)
    corpus_path = Path(args.corpus)
    artifact_dir = manifest_path.parent
    if corpus_path.resolve() != (artifact_dir / "corpus.jsonl").resolve():
        raise ValueError("corpus and manifest must belong to the same tracked artifact directory")
    records = load_verified_corpus(artifact_dir)
    eval_set = load_and_validate_eval_set(args.eval_set, manifest_path)
    items = select_questions(
        eval_set,
        split=args.split,
        allow_heldout=args.split == "heldout",
    )
    spec = load_model_spec(args.model_manifest)
    embedding = ExperimentEmbedding(args.model_dir, args.model_manifest, spec)
    provenance = build_provenance(
        code_commit=args.code_commit,
        corpus_path=corpus_path,
        manifest_path=manifest_path,
        eval_set_path=args.eval_set,
        embedding=embedding,
    )
    configs = DEFAULT_CONFIGS
    if args.split == "heldout":
        if not args.freeze:
            raise ValueError("heldout requires --freeze")
        configs = (validate_heldout_gate(args.freeze, provenance, args.out),)
    _, service = _make_service(records, embedding)
    rows = _evaluate(items, configs, service)
    summary = aggregate_by_config(rows)
    selected = choose_best_config(configs, summary) if args.split == "development" else configs[0]
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "split": args.split,
        "n_questions": len(items),
        "n_corpus_chunks": len(records),
        "provenance": provenance,
        "configs": [config.to_dict() for config in configs],
        "preregistered_selection_rule": [
            "hit_rate_at_5",
            "mrr_at_10",
            "recall_at_5",
            "lower_dependency_cost_on_exact_quality_tie",
            "lower_median_latency",
        ],
        "selected_config": selected.to_dict(),
        "reranker": {
            "status": "not_evaluated",
            "reason": "no verified cross-encoder snapshot in the reproducible image",
        },
        "summary": summary,
        "rows": rows,
    }
    write_new_result(args.out, result)
    print(json.dumps({"out": args.out, "selected": selected.name, "summary": summary}, ensure_ascii=False, indent=2))


def freeze_result(args: argparse.Namespace) -> None:
    result = json.loads(Path(args.development).read_text(encoding="utf-8"))
    configs = [ExperimentConfig.from_dict(value) for value in result.get("configs", [])]
    if args.config == "auto":
        selected = choose_best_config(configs, result.get("summary", {}))
    else:
        selected = next((value for value in configs if value.name == args.config), None)
        if selected is None:
            raise ValueError(f"config not found in development result: {args.config}")
    frozen = freeze_development_result(args.development, args.out, selected)
    print(json.dumps(frozen, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--split", choices=("development", "heldout"), default="development")
    run.add_argument("--corpus", default="kb_v2/build/corpus.jsonl")
    run.add_argument("--manifest", default="kb_v2/build/manifest.json")
    run.add_argument("--eval-set", default="eval/eval_set.json")
    run.add_argument("--model-dir", required=True)
    run.add_argument("--model-manifest", required=True)
    run.add_argument("--code-commit", required=True)
    run.add_argument("--freeze")
    run.add_argument("--out", required=True)
    run.set_defaults(handler=run_experiment)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--development", required=True)
    freeze.add_argument("--config", default="auto")
    freeze.add_argument("--out", required=True)
    freeze.set_defaults(handler=freeze_result)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
