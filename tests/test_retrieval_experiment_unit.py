from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from retrieval_experiment import (
    ExperimentConfig,
    ExperimentGateError,
    aggregate_by_config,
    choose_best_config,
    freeze_development_result,
    validate_heldout_gate,
)


def config(name: str = "hybrid-1-2") -> ExperimentConfig:
    return ExperimentConfig(
        name=name,
        strategy="hybrid",
        top_k=10,
        dense_weight=1.0,
        sparse_weight=2.0,
    )


def provenance() -> dict:
    return {
        "code_commit": "abc1234",
        "corpus_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
        "eval_set_sha256": "3" * 64,
        "embedding_model_id": "sentence-transformers/model",
        "embedding_model_revision": "revision-1",
        "embedding_pooling": "masked_mean",
        "embedding_snapshot_sha256": "4" * 64,
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"strategy": "unknown"}, "strategy"),
        ({"top_k": 0}, "top_k"),
        ({"dense_weight": 0}, "dense_weight"),
        ({"sparse_weight": -1}, "sparse_weight"),
    ],
)
def test_experiment_config_rejects_values_that_cannot_reach_production(
    kwargs: dict, message: str
) -> None:
    values = {
        "name": "candidate",
        "strategy": "hybrid",
        "top_k": 10,
        "dense_weight": 1.0,
        "sparse_weight": 2.0,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        ExperimentConfig(**values)


def test_aggregate_reports_scored_unscored_errors_categories_and_latency() -> None:
    rows = [
        {
            "config": "hybrid-1-2",
            "category": "exact",
            "elapsed_ms": 10.0,
            "outcome": {
                "status": "ok",
                "metrics": {
                    "recall_at_5": 1.0,
                    "recall_at_10": 1.0,
                    "mrr_at_10": 0.5,
                    "hit_rate_at_5": 1.0,
                },
            },
        },
        {
            "config": "hybrid-1-2",
            "category": "exact",
            "elapsed_ms": 30.0,
            "outcome": {"status": "unscored", "reason": "no ground truth"},
        },
        {
            "config": "hybrid-1-2",
            "category": "semantic",
            "elapsed_ms": 20.0,
            "outcome": {"status": "error", "reason": "broken"},
        },
    ]

    summary = aggregate_by_config(rows)["hybrid-1-2"]

    assert summary["counts"] == {
        "total": 3,
        "scored": 1,
        "ok": 1,
        "empty": 0,
        "unscored": 1,
        "fallback": 0,
        "error": 1,
    }
    assert summary["metrics"] == {
        "recall_at_5": 1.0,
        "recall_at_10": 1.0,
        "mrr_at_10": 0.5,
        "hit_rate_at_5": 1.0,
    }
    assert summary["latency_ms"] == {"median": 20.0, "p95": 30.0}
    assert summary["categories"]["exact"]["counts"]["scored"] == 1
    assert summary["categories"]["semantic"]["counts"]["error"] == 1


def test_choose_best_config_uses_preregistered_metric_order_then_latency() -> None:
    configs = [
        ExperimentConfig("dense", "dense", 10, 1.0, 1.0),
        ExperimentConfig("hybrid-1-1", "hybrid", 10, 1.0, 1.0),
        ExperimentConfig("hybrid-1-2", "hybrid", 10, 1.0, 2.0),
    ]
    summary = {
        "dense": {
            "counts": {"scored": 22, "error": 0, "fallback": 0},
            "metrics": {"hit_rate_at_5": 0.9, "mrr_at_10": 0.7, "recall_at_5": 0.8},
            "latency_ms": {"median": 10.0},
        },
        "hybrid-1-1": {
            "counts": {"scored": 22, "error": 0, "fallback": 0},
            "metrics": {"hit_rate_at_5": 0.95, "mrr_at_10": 0.75, "recall_at_5": 0.7},
            "latency_ms": {"median": 15.0},
        },
        "hybrid-1-2": {
            "counts": {"scored": 22, "error": 0, "fallback": 0},
            "metrics": {"hit_rate_at_5": 0.95, "mrr_at_10": 0.8, "recall_at_5": 0.6},
            "latency_ms": {"median": 20.0},
        },
    }

    assert choose_best_config(configs, summary).name == "hybrid-1-2"


def test_choose_best_config_rejects_failed_candidate_even_with_high_metrics() -> None:
    failed = ExperimentConfig("failed", "hybrid", 10, 1.0, 2.0)
    valid = ExperimentConfig("valid", "dense", 10, 1.0, 1.0)
    summary = {
        "failed": {
            "counts": {"scored": 22, "error": 1, "fallback": 0},
            "metrics": {"hit_rate_at_5": 1.0, "mrr_at_10": 1.0, "recall_at_5": 1.0},
            "latency_ms": {"median": 1.0},
        },
        "valid": {
            "counts": {"scored": 22, "error": 0, "fallback": 0},
            "metrics": {"hit_rate_at_5": 0.8, "mrr_at_10": 0.7, "recall_at_5": 0.6},
            "latency_ms": {"median": 5.0},
        },
    }

    assert choose_best_config([failed, valid], summary) == valid


def write_development_result(path: Path) -> dict:
    payload = {
        "schema_version": 1,
        "split": "development",
        "provenance": provenance(),
        "configs": [config().to_dict()],
        "summary": {
            "hybrid-1-2": {
                "counts": {"total": 24, "scored": 22, "error": 0},
                "metrics": {
                    "hit_rate_at_5": 0.9,
                    "mrr_at_10": 0.8,
                    "recall_at_5": 0.7,
                },
            }
        },
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload


def test_freeze_records_exact_development_result_and_chosen_config(tmp_path: Path) -> None:
    development = tmp_path / "development.json"
    payload = write_development_result(development)
    freeze = tmp_path / "freeze.json"

    frozen = freeze_development_result(development, freeze, config())

    assert frozen["status"] == "frozen"
    assert frozen["split"] == "development"
    assert frozen["chosen_config"] == config().to_dict()
    assert frozen["provenance"] == payload["provenance"]
    assert frozen["development_result_sha256"] == hashlib.sha256(
        development.read_bytes()
    ).hexdigest()


def test_freeze_refuses_unknown_or_failed_candidate(tmp_path: Path) -> None:
    development = tmp_path / "development.json"
    write_development_result(development)

    with pytest.raises(ExperimentGateError, match="chosen config"):
        freeze_development_result(
            development, tmp_path / "freeze.json", config("not-evaluated")
        )


def test_heldout_requires_freeze_with_identical_provenance(tmp_path: Path) -> None:
    output = tmp_path / "heldout.json"
    missing = tmp_path / "missing-freeze.json"

    with pytest.raises(ExperimentGateError, match="freeze"):
        validate_heldout_gate(missing, provenance(), output)

    development = tmp_path / "development.json"
    write_development_result(development)
    freeze = tmp_path / "freeze.json"
    freeze_development_result(development, freeze, config())
    drifted = provenance()
    drifted["eval_set_sha256"] = "9" * 64

    with pytest.raises(ExperimentGateError, match="provenance"):
        validate_heldout_gate(freeze, drifted, output)


def test_heldout_gate_refuses_overwrite_and_returns_frozen_config(tmp_path: Path) -> None:
    development = tmp_path / "development.json"
    write_development_result(development)
    freeze = tmp_path / "freeze.json"
    freeze_development_result(development, freeze, config())
    output = tmp_path / "heldout.json"

    assert validate_heldout_gate(freeze, provenance(), output) == config()

    output.write_text("already consumed", encoding="utf-8")
    with pytest.raises(ExperimentGateError, match="already exists"):
        validate_heldout_gate(freeze, provenance(), output)
