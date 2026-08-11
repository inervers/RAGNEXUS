"""Verified, padding-safe embedding runtime shared by API and experiments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

POOLING_MODES = {"legacy_mean", "masked_mean"}
PROVENANCE_FIELDS = (
    "embedding_model_id",
    "embedding_model_revision",
    "embedding_pooling",
    "embedding_snapshot_sha256",
)


class PoolingConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    revision: str
    pooling: str

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id must be a non-empty string")
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError("revision must be a non-empty string")
        if self.pooling not in POOLING_MODES:
            raise ValueError(f"pooling must be one of {sorted(POOLING_MODES)}")

    @classmethod
    def from_manifest(cls, manifest_path: str | Path) -> "ModelSpec":
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        return cls(
            model_id=manifest["model_id"],
            revision=manifest["revision"],
            pooling=manifest["pooling"],
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def provenance(self, snapshot_sha256: str) -> dict[str, str]:
        return {
            "embedding_model_id": self.model_id,
            "embedding_model_revision": self.revision,
            "embedding_pooling": self.pooling,
            "embedding_snapshot_sha256": snapshot_sha256,
        }


@dataclass(frozen=True)
class EmbeddingRuntimeConfig:
    snapshot_dir: Path
    manifest_path: Path
    spec: ModelSpec


def _resolve_from_base(raw_path: str, base_dir: Path) -> Path:
    path = Path(raw_path)
    return (path if path.is_absolute() else base_dir / path).resolve()


def resolve_embedding_runtime_config(
    environ: Mapping[str, str], base_dir: str | Path
) -> EmbeddingRuntimeConfig:
    root = Path(base_dir).resolve()
    snapshot_dir = _resolve_from_base(
        environ.get(
            "RAG_EMBEDDING_MODEL_SOURCE",
            ".rag06-models/multilingual-minilm-l12-v2",
        ),
        root,
    )
    manifest_path = _resolve_from_base(
        environ.get(
            "RAG_EMBEDDING_MANIFEST",
            "models/manifests/paraphrase-multilingual-MiniLM-L12-v2.json",
        ),
        root,
    )
    spec = ModelSpec.from_manifest(manifest_path)
    overrides = {
        "RAG_EMBEDDING_MODEL_ID": spec.model_id,
        "RAG_EMBEDDING_MODEL_REVISION": spec.revision,
        "RAG_EMBEDDING_POOLING": spec.pooling,
    }
    for variable, manifest_value in overrides.items():
        configured = environ.get(variable)
        if configured is not None and configured.strip() != manifest_value:
            raise ValueError(
                f"{variable}={configured!r} does not match embedding manifest "
                f"value {manifest_value!r}"
            )
    return EmbeddingRuntimeConfig(snapshot_dir, manifest_path, spec)


def resolve_pooling_mode(raw_value: str | None) -> str:
    mode = (raw_value or "legacy_mean").strip().lower()
    if mode not in POOLING_MODES:
        raise PoolingConfigurationError(
            f"RAG_EMBEDDING_POOLING must be one of {sorted(POOLING_MODES)}"
        )
    return mode


def embedding_function_name(mode: str) -> str:
    mode = resolve_pooling_mode(mode)
    if mode == "legacy_mean":
        return "MiniLM-L6-v2-mean-pooling"
    return "MiniLM-L6-v2-masked_mean-v1"


def validate_collection_pooling(
    mode: str, count: int, metadata: dict | None
) -> None:
    stored_mode = (metadata or {}).get("embedding_pooling")
    if count == 0:
        return
    if stored_mode is None and mode == "legacy_mean":
        return
    if stored_mode != mode:
        actual = stored_mode or "unknown legacy_mean"
        raise PoolingConfigurationError(
            f"collection embedding_pooling={actual}, runtime={mode}; "
            "re-embed into a new collection before switching"
        )


def validate_collection_provenance(
    expected: dict[str, str], count: int, metadata: dict | None
) -> None:
    """Reject a non-empty collection built in a different vector space."""
    if count == 0:
        return
    stored = metadata or {}
    if not any(field in stored for field in PROVENANCE_FIELDS):
        if expected.get("embedding_pooling") == "legacy_mean":
            return
        raise PoolingConfigurationError(
            "collection embedding provenance is unknown; re-embed into a new "
            "collection before switching"
        )
    if set(stored).intersection(PROVENANCE_FIELDS) == {"embedding_pooling"}:
        validate_collection_pooling(
            expected.get("embedding_pooling", ""), count, stored
        )
        if expected.get("embedding_pooling") == "legacy_mean":
            return
    for field in PROVENANCE_FIELDS:
        actual = stored.get(field)
        wanted = expected.get(field)
        if actual != wanted:
            raise PoolingConfigurationError(
                f"collection {field}={actual or 'unknown'}, runtime={wanted}; "
                "re-embed into a new collection before switching"
            )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_snapshot(snapshot_dir: str | Path, manifest_path: str | Path) -> str:
    root = Path(snapshot_dir).resolve()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("snapshot manifest files must be a non-empty list")
    verified = []
    for item in files:
        relative = Path(item.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"unsafe snapshot path: {relative}")
        target = (root / relative).resolve()
        if root not in target.parents:
            raise ValueError(f"snapshot path escapes root: {relative}")
        if not target.is_file():
            raise ValueError(f"snapshot file missing: {relative.as_posix()}")
        size = target.stat().st_size
        digest = _file_sha256(target)
        if size != item.get("size"):
            raise ValueError(f"size mismatch for {relative.as_posix()}")
        if digest != item.get("sha256"):
            raise ValueError(f"SHA256 mismatch for {relative.as_posix()}")
        verified.append(
            {"path": relative.as_posix(), "size": size, "sha256": digest}
        )
    canonical = json.dumps(
        sorted(verified, key=lambda value: value["path"]),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def masked_mean_pool(last_hidden_state, attention_mask):
    expanded_mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size())
    expanded_mask = expanded_mask.to(
        device=last_hidden_state.device, dtype=last_hidden_state.dtype
    )
    token_sum = (last_hidden_state * expanded_mask).sum(dim=1)
    token_count = expanded_mask.sum(dim=1).clamp(min=1e-9)
    return token_sum / token_count


def embed_batch(
    texts,
    tokenizer,
    model,
    torch_module,
    max_length: int = 256,
    pooling: str = "masked_mean",
):
    pooling = resolve_pooling_mode(pooling)
    inputs = tokenizer(
        texts,
        truncation=True,
        padding=True,
        return_tensors="pt",
        max_length=max_length,
    )
    with torch_module.no_grad():
        hidden = model(**inputs).last_hidden_state
        pooled = (
            hidden.mean(dim=1)
            if pooling == "legacy_mean"
            else masked_mean_pool(hidden, inputs["attention_mask"])
        )
        normalized = torch_module.nn.functional.normalize(pooled, p=2, dim=1)
    return normalized.cpu().numpy()


class VerifiedEmbedding:
    """Chroma-compatible local embedding with immutable snapshot provenance."""

    def __init__(
        self,
        snapshot_dir: str | Path,
        manifest_path: str | Path,
        spec: ModelSpec | None = None,
    ) -> None:
        from transformers import AutoModel, AutoTokenizer

        manifest_spec = ModelSpec.from_manifest(manifest_path)
        if spec is not None and spec != manifest_spec:
            raise ValueError(
                f"runtime model spec {spec.to_dict()} does not match manifest "
                f"{manifest_spec.to_dict()}"
            )
        self.spec = manifest_spec
        self.snapshot_sha256 = verify_snapshot(snapshot_dir, manifest_path)
        model_path = str(Path(snapshot_dir).resolve())
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path, local_files_only=True
        )
        self.model = AutoModel.from_pretrained(model_path, local_files_only=True)
        self.model.eval()

    def _embed(self, texts: list[str]):
        import torch

        return embed_batch(
            texts,
            self.tokenizer,
            self.model,
            torch,
            pooling=self.spec.pooling,
        )

    def __call__(self, input):
        if isinstance(input, (list, tuple)):
            texts = [item.text if hasattr(item, "text") else str(item) for item in input]
        else:
            texts = [input.text if hasattr(input, "text") else str(input)]
        return [vector.tolist() for vector in self._embed(texts)]

    def embed_query(self, input):
        return self.__call__(input)

    def name(self) -> str:
        model_slug = re.sub(r"[^a-z0-9]+", "-", self.spec.model_id.lower()).strip("-")
        return f"{model_slug}-{self.spec.pooling}-{self.snapshot_sha256[:12]}"

    def provenance(self) -> dict[str, str]:
        return self.spec.provenance(self.snapshot_sha256)
