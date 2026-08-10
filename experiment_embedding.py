"""Verified local embedding runtime used only by isolated RAG-06 experiments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


POOLING_MODES = {"legacy_mean", "masked_mean"}


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

    def to_dict(self) -> dict:
        return asdict(self)


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
    expanded_mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    token_sum = (last_hidden_state * expanded_mask).sum(dim=1)
    token_count = expanded_mask.sum(dim=1).clamp(min=1e-9)
    return token_sum / token_count


class ExperimentEmbedding:
    """Chroma-compatible embedding function with explicit pooling provenance."""

    def __init__(
        self,
        snapshot_dir: str | Path,
        manifest_path: str | Path,
        spec: ModelSpec,
    ) -> None:
        from transformers import AutoModel, AutoTokenizer

        self.spec = spec
        self.snapshot_sha256 = verify_snapshot(snapshot_dir, manifest_path)
        model_path = str(Path(snapshot_dir).resolve())
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path, local_files_only=True
        )
        self.model = AutoModel.from_pretrained(model_path, local_files_only=True)
        self.model.eval()

    def _embed(self, texts: list[str]):
        import torch

        inputs = self.tokenizer(
            texts,
            truncation=True,
            padding=True,
            return_tensors="pt",
            max_length=256,
        )
        with torch.no_grad():
            hidden = self.model(**inputs).last_hidden_state
            if self.spec.pooling == "legacy_mean":
                pooled = hidden.mean(dim=1)
            else:
                pooled = masked_mean_pool(hidden, inputs["attention_mask"])
            normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return normalized.numpy()

    def __call__(self, input):
        if isinstance(input, (list, tuple)):
            texts = [item.text if hasattr(item, "text") else str(item) for item in input]
        else:
            texts = [input.text if hasattr(input, "text") else str(input)]
        return [vector.tolist() for vector in self._embed(texts)]

    def embed_query(self, input):
        """Match ChromaDB 1.5.x's query-side EmbeddingFunction contract."""
        return self.__call__(input)

    def name(self) -> str:
        short_hash = self.snapshot_sha256[:12]
        return f"rag06-{self.spec.pooling}-{short_hash}"

    def provenance(self) -> dict:
        return {
            "embedding_model_id": self.spec.model_id,
            "embedding_model_revision": self.spec.revision,
            "embedding_pooling": self.spec.pooling,
            "embedding_snapshot_sha256": self.snapshot_sha256,
        }
