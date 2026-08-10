"""Contracts, aggregation, and heldout gates for RAG-06 experiments."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


METRIC_NAMES = (
    "recall_at_5",
    "recall_at_10",
    "mrr_at_10",
    "hit_rate_at_5",
)
STATUSES = ("ok", "empty", "unscored", "fallback", "error")
PROVENANCE_FIELDS = (
    "code_commit",
    "corpus_sha256",
    "manifest_sha256",
    "eval_set_sha256",
    "embedding_model_id",
    "embedding_model_revision",
    "embedding_pooling",
    "embedding_snapshot_sha256",
)


class ExperimentGateError(RuntimeError):
    """Raised when an experiment would violate its preregistered boundary."""


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    strategy: str
    top_k: int = 10
    dense_weight: float = 1.0
    sparse_weight: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if self.strategy not in {"dense", "hybrid", "reranked"}:
            raise ValueError("strategy must be dense, hybrid, or reranked")
        if not isinstance(self.top_k, int) or not 1 <= self.top_k <= 50:
            raise ValueError("top_k must be an integer in 1..50")
        if self.dense_weight <= 0:
            raise ValueError("dense_weight must be positive")
        if self.sparse_weight <= 0:
            raise ValueError("sparse_weight must be positive")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "ExperimentConfig":
        return cls(**{field: value[field] for field in cls.__dataclass_fields__})


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _avg(values: Iterable[float]) -> float | None:
    materialized = list(values)
    if not materialized:
        return None
    return round(sum(materialized) / len(materialized), 4)


def _percentile_nearest_rank(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(float(ordered[index]), 3)


def _aggregate_rows(rows: list[dict], *, include_categories: bool) -> dict:
    counts = {"total": len(rows), "scored": 0, **{status: 0 for status in STATUSES}}
    metric_values = {metric: [] for metric in METRIC_NAMES}
    latencies = []
    for row in rows:
        elapsed = row.get("elapsed_ms")
        if isinstance(elapsed, (int, float)):
            latencies.append(float(elapsed))
        outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
        status = outcome.get("status", "error")
        if status not in STATUSES:
            status = "error"
        counts[status] += 1
        if status not in {"ok", "empty"}:
            continue
        counts["scored"] += 1
        metrics = outcome.get("metrics") if isinstance(outcome.get("metrics"), dict) else {}
        for metric in METRIC_NAMES:
            value = metrics.get(metric)
            if isinstance(value, (int, float)):
                metric_values[metric].append(float(value))
    result = {
        "counts": counts,
        "metrics": {metric: _avg(values) for metric, values in metric_values.items()},
        "latency_ms": {
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p95": _percentile_nearest_rank(latencies, 0.95),
        },
    }
    if include_categories:
        categories = sorted({row.get("category", "unknown") for row in rows})
        result["categories"] = {
            category: _aggregate_rows(
                [row for row in rows if row.get("category", "unknown") == category],
                include_categories=False,
            )
            for category in categories
        }
    return result


def aggregate_by_config(rows: Iterable[dict]) -> dict:
    materialized = list(rows)
    names = sorted({row.get("config") for row in materialized if row.get("config")})
    return {
        name: _aggregate_rows(
            [row for row in materialized if row.get("config") == name],
            include_categories=True,
        )
        for name in names
    }


def choose_best_config(
    configs: Iterable[ExperimentConfig], summary: dict
) -> ExperimentConfig:
    """Apply the preregistered quality order, then prefer lower median latency."""
    eligible = []
    for config in configs:
        candidate = summary.get(config.name)
        if not isinstance(candidate, dict):
            continue
        counts = candidate.get("counts", {})
        metrics = candidate.get("metrics", {})
        if counts.get("scored", 0) <= 0 or counts.get("error", 0) or counts.get("fallback", 0):
            continue
        quality = tuple(metrics.get(name) for name in (
            "hit_rate_at_5",
            "mrr_at_10",
            "recall_at_5",
        ))
        if not all(isinstance(value, (int, float)) for value in quality):
            continue
        median = candidate.get("latency_ms", {}).get("median")
        latency_rank = -float(median) if isinstance(median, (int, float)) else float("-inf")
        eligible.append((quality + (latency_rank, config.name), config))
    if not eligible:
        raise ExperimentGateError("no successful scored candidate is eligible")
    return max(eligible, key=lambda item: item[0])[1]


def _write_new_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise ExperimentGateError(f"output already exists: {path}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(serialized)


def _validate_provenance(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ExperimentGateError("provenance must be an object")
    missing = [field for field in PROVENANCE_FIELDS if not value.get(field)]
    if missing:
        raise ExperimentGateError(f"provenance missing fields: {', '.join(missing)}")
    return {field: value[field] for field in PROVENANCE_FIELDS}


def freeze_development_result(
    development_result_path: str | Path,
    freeze_path: str | Path,
    chosen_config: ExperimentConfig,
) -> dict:
    development_path = Path(development_result_path)
    try:
        result = json.loads(development_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentGateError(f"cannot read development result: {exc}") from exc
    if result.get("split") != "development":
        raise ExperimentGateError("freeze requires a development result")
    chosen = chosen_config.to_dict()
    if chosen not in result.get("configs", []):
        raise ExperimentGateError("chosen config was not evaluated")
    summary = result.get("summary", {}).get(chosen_config.name)
    if not isinstance(summary, dict):
        raise ExperimentGateError("chosen config has no summary")
    counts = summary.get("counts", {})
    if counts.get("scored", 0) <= 0 or counts.get("error", 0) or counts.get("fallback", 0):
        raise ExperimentGateError("chosen config is not a successful scored candidate")
    frozen = {
        "schema_version": 1,
        "status": "frozen",
        "split": "development",
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection_rule": ["hit_rate_at_5", "mrr_at_10", "recall_at_5"],
        "chosen_config": chosen,
        "chosen_summary": summary,
        "provenance": _validate_provenance(result.get("provenance")),
        "development_result": str(development_path),
        "development_result_sha256": sha256_file(development_path),
    }
    _write_new_json(Path(freeze_path), frozen)
    return frozen


def validate_heldout_gate(
    freeze_path: str | Path,
    current_provenance: dict,
    heldout_output_path: str | Path,
) -> ExperimentConfig:
    output = Path(heldout_output_path)
    if output.exists():
        raise ExperimentGateError(f"heldout output already exists: {output}")
    try:
        frozen = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentGateError(f"cannot read freeze: {exc}") from exc
    if frozen.get("status") != "frozen" or frozen.get("split") != "development":
        raise ExperimentGateError("freeze is not in the frozen development state")
    expected = _validate_provenance(frozen.get("provenance"))
    actual = _validate_provenance(current_provenance)
    if actual != expected:
        raise ExperimentGateError("current provenance does not match frozen provenance")
    try:
        return ExperimentConfig.from_dict(frozen["chosen_config"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperimentGateError(f"invalid chosen config in freeze: {exc}") from exc


def write_new_result(path: str | Path, payload: dict) -> None:
    """Public exclusive writer used by the runner for non-overwritable evidence."""
    _write_new_json(Path(path), payload)
