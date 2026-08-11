"""Deterministic source projection for the RAGNEXUS V2 knowledge corpus.

This module is intentionally stdlib-only.  It does not import ChromaDB,
embedding models, the API service, or any runtime database state.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import math
import tempfile
from typing import Any
import unicodedata


class CatalogError(ValueError):
    """Raised when corpus source declarations are ambiguous or unsafe."""


REQUIRED_FIELDS = (
    "doc_id",
    "title",
    "project",
    "source_type",
    "version",
    "commit",
    "updated_at",
    "authority",
    "source",
    "status",
    "sensitivity",
    "sections",
)


@dataclass(frozen=True)
class CatalogEntry:
    doc_id: str
    title: str
    project: str
    source_type: str
    version: str
    commit: str
    updated_at: str
    authority: str
    source: str
    status: str
    sensitivity: str
    sections: tuple[str, ...]


@dataclass(frozen=True)
class ProjectedSection:
    path: str
    text: str


@dataclass(frozen=True)
class ProjectedDocument:
    entry: CatalogEntry
    source_sha256: str
    sections: tuple[ProjectedSection, ...]

    @property
    def doc_id(self) -> str:
        return self.entry.doc_id

    @property
    def title(self) -> str:
        return self.entry.title


@dataclass(frozen=True)
class ProjectionResult:
    documents: tuple[ProjectedDocument, ...]
    excluded: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class BuildResult:
    corpus_path: Path
    manifest_path: Path
    logical_document_count: int
    chunk_count: int


def _read_catalog_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read catalog {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
        raise CatalogError("catalog must contain a documents array")
    return payload


def load_catalog(path: str | Path) -> tuple[CatalogEntry, ...]:
    catalog_path = Path(path)
    payload = _read_catalog_payload(catalog_path)
    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for index, raw in enumerate(payload["documents"]):
        if not isinstance(raw, dict):
            raise CatalogError(f"documents[{index}] must be an object")
        missing = [field for field in REQUIRED_FIELDS if field not in raw]
        if missing:
            raise CatalogError(f"documents[{index}] missing required fields: {', '.join(missing)}")
        values = {field: raw[field] for field in REQUIRED_FIELDS}
        scalar_fields = REQUIRED_FIELDS[:-1]
        invalid = [field for field in scalar_fields if not isinstance(values[field], str) or not values[field].strip()]
        if invalid:
            raise CatalogError(f"documents[{index}] invalid string fields: {', '.join(invalid)}")
        sections = values["sections"]
        if not isinstance(sections, list) or not sections or any(
            not isinstance(section, str) or not section.strip() for section in sections
        ):
            raise CatalogError(f"documents[{index}] sections must be a non-empty string array")
        doc_id = values["doc_id"]
        if doc_id in seen:
            raise CatalogError(f"duplicate doc_id: {doc_id}")
        seen.add(doc_id)
        entries.append(
            CatalogEntry(
                **{field: values[field].strip() for field in scalar_fields},
                sections=tuple(section.strip() for section in sections),
            )
        )
    return tuple(entries)


def _allowed_roots(catalog_path: Path, payload: dict[str, Any]) -> tuple[Path, ...]:
    declared = payload.get("source_roots", ["."])
    if not isinstance(declared, list) or not declared or any(not isinstance(item, str) for item in declared):
        raise CatalogError("source_roots must be a non-empty string array")
    return tuple((catalog_path.parent / item).resolve() for item in declared)


def _resolve_source(catalog_path: Path, entry: CatalogEntry, roots: tuple[Path, ...]) -> Path:
    declared = Path(entry.source)
    if declared.is_absolute():
        raise CatalogError(f"absolute source path is forbidden for {entry.doc_id}")
    resolved = (catalog_path.parent / declared).resolve()
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise CatalogError(f"source escapes allowed roots for {entry.doc_id}: {entry.source}")
    return resolved


def _markdown_h2_sections(text: str, source: str) -> dict[str, str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip()
            if current in sections:
                raise CatalogError(f"duplicate H2 heading {current!r} in {source}")
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {heading: "\n".join(body).strip() for heading, body in sections.items()}


def project_catalog(path: str | Path) -> ProjectionResult:
    catalog_path = Path(path)
    payload = _read_catalog_payload(catalog_path)
    entries = load_catalog(catalog_path)
    roots = _allowed_roots(catalog_path, payload)
    documents: list[ProjectedDocument] = []
    excluded: list[dict[str, str]] = []
    for entry in entries:
        reasons: list[str] = []
        if entry.status != "current":
            reasons.append(f"status={entry.status}")
        if entry.sensitivity != "public":
            reasons.append(f"sensitivity={entry.sensitivity}")
        if reasons:
            excluded.append({"doc_id": entry.doc_id, "reason": ",".join(reasons)})
            continue

        source_path = _resolve_source(catalog_path, entry, roots)
        try:
            source_bytes = source_path.read_bytes()
            source_text = source_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CatalogError(f"cannot read source for {entry.doc_id}: {entry.source}: {exc}") from exc
        available = _markdown_h2_sections(source_text, entry.source)
        selected: list[ProjectedSection] = []
        for heading in entry.sections:
            if heading not in available:
                raise CatalogError(f"missing declared heading {heading!r} for {entry.doc_id}")
            selected.append(ProjectedSection(path=heading, text=available[heading]))
        documents.append(
            ProjectedDocument(
                entry=entry,
                source_sha256=hashlib.sha256(source_bytes).hexdigest(),
                sections=tuple(selected),
            )
        )
    return ProjectionResult(documents=tuple(documents), excluded=tuple(excluded))


def normalize_text(text: str) -> str:
    """Normalize identity-relevant text without flattening code indentation."""

    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    output: list[str] = []
    blank = False
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            output.append(line)
            in_fence = not in_fence
            blank = False
            continue
        if in_fence:
            output.append(line)
            continue
        if not line:
            if output and not blank:
                output.append("")
            blank = True
            continue
        output.append(line)
        blank = False
    while output and not output[-1]:
        output.pop()
    return "\n".join(output).strip()


_TOKEN_PARTS = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]")


def estimate_tokens(text: str) -> int:
    """Return a conservative deterministic estimate, not a model token count."""

    count = 0
    for part in _TOKEN_PARTS.findall(text):
        if re.fullmatch(r"[A-Za-z0-9_]+", part):
            count += math.ceil(len(part) / 4)
        else:
            count += 1
    return count


def make_chunk_id(doc_id: str, text: str) -> str:
    normalized = normalize_text(text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{doc_id}#{digest[:16]}"


def _paragraph_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in normalize_text(text).split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            current.append(line)
            continue
        if not line and not in_fence:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def _sentence_units(text: str) -> list[str]:
    units = [part.strip() for part in re.findall(r".*?(?:[。！？!?；;]\s*|\n+|$)", text, flags=re.S)]
    return [unit for unit in units if unit]


def _hard_split(text: str, budget: int) -> list[str]:
    atoms = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9_]+|\s+|.", text, flags=re.S)
    pieces: list[str] = []
    current = ""
    for atom in atoms:
        if estimate_tokens(atom) > budget:
            if current.strip():
                pieces.append(current.strip())
                current = ""
            if re.fullmatch(r"[A-Za-z0-9_]+", atom):
                width = budget * 4
                pieces.extend(atom[start : start + width] for start in range(0, len(atom), width))
                continue
        candidate = current + atom
        if current and estimate_tokens(candidate) > budget:
            pieces.append(current.strip())
            current = atom.lstrip()
        else:
            current = candidate
    if current.strip():
        pieces.append(current.strip())
    return pieces


def _fit_units(text: str, budget: int) -> list[str]:
    if estimate_tokens(text) <= budget:
        return [text]
    fitted: list[str] = []
    for sentence in _sentence_units(text):
        if estimate_tokens(sentence) <= budget:
            fitted.append(sentence)
        else:
            fitted.extend(_hard_split(sentence, budget))
    return fitted


def _tail_overlap(units: list[str], budget: int) -> list[str]:
    if budget <= 0:
        return []
    selected: list[str] = []
    for unit in reversed(units):
        candidate = [unit, *selected]
        if estimate_tokens("\n\n".join(candidate)) > budget:
            break
        selected = candidate
    return selected


def chunk_projected_document(
    document: ProjectedDocument,
    *,
    max_tokens: int = 220,
    overlap_tokens: int = 30,
) -> tuple[dict[str, Any], ...]:
    if max_tokens <= 0 or overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise CatalogError("chunk budgets must satisfy max_tokens > overlap_tokens >= 0")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for section in document.sections:
        prefix = normalize_text(f"# {document.title}\n\n## {section.path}")
        body_budget = max_tokens - estimate_tokens(prefix)
        if body_budget <= 0:
            raise CatalogError(f"heading context exceeds max_tokens for {document.doc_id}: {section.path}")
        units: list[str] = []
        for block in _paragraph_blocks(section.text):
            units.extend(_fit_units(block, body_budget))
        if not units:
            raise CatalogError(f"empty projected section for {document.doc_id}: {section.path}")

        groups: list[list[str]] = []
        current: list[str] = []
        for unit in units:
            candidate = [*current, unit]
            if current and estimate_tokens("\n\n".join(candidate)) > body_budget:
                groups.append(current)
                current = _tail_overlap(current, min(overlap_tokens, body_budget - 1))
                while current and estimate_tokens("\n\n".join([*current, unit])) > body_budget:
                    current.pop(0)
            current.append(unit)
        if current:
            groups.append(current)

        for group in groups:
            group_text = "\n\n".join(group)
            chunk_text = normalize_text(f"{prefix}\n\n{group_text}")
            chunk_id = make_chunk_id(document.doc_id, chunk_text)
            if chunk_id in seen_ids:
                raise CatalogError(f"duplicate chunk identity for {document.doc_id}: {chunk_id}")
            seen_ids.add(chunk_id)
            content_sha256 = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            entry = document.entry
            metadata: dict[str, Any] = {
                "doc_id": entry.doc_id,
                "chunk_id": chunk_id,
                "title": entry.title,
                "project": entry.project,
                "source_type": entry.source_type,
                "version": entry.version,
                "commit": entry.commit,
                "updated_at": entry.updated_at,
                "authority": entry.authority,
                "source": entry.source,
                "status": entry.status,
                "sensitivity": entry.sensitivity,
                "section_path": section.path,
                "chunk_index": len(records),
                "source_sha256": document.source_sha256,
                "content_sha256": content_sha256,
            }
            records.append({"id": chunk_id, "document": chunk_text, "metadata": metadata})
    return tuple(records)


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def build_artifacts(
    catalog_path: str | Path,
    output_dir: str | Path,
    *,
    max_tokens: int = 220,
    overlap_tokens: int = 30,
) -> BuildResult:
    catalog = Path(catalog_path)
    output = Path(output_dir)
    projection = project_catalog(catalog)
    all_records: list[dict[str, Any]] = []
    manifest_documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for document in projection.documents:
        records = list(
            chunk_projected_document(
                document,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
            )
        )
        duplicate = seen_ids.intersection(record["id"] for record in records)
        if duplicate:
            raise CatalogError(f"duplicate corpus chunk IDs: {sorted(duplicate)}")
        seen_ids.update(record["id"] for record in records)
        all_records.extend(records)
        projected_content = normalize_text(
            "\n\n".join(f"## {section.path}\n\n{section.text}" for section in document.sections)
        )
        manifest_documents.append(
            {
                "doc_id": document.doc_id,
                "title": document.title,
                "project": document.entry.project,
                "source_type": document.entry.source_type,
                "version": document.entry.version,
                "commit": document.entry.commit,
                "source": document.entry.source,
                "source_sha256": document.source_sha256,
                "content_sha256": hashlib.sha256(projected_content.encode("utf-8")).hexdigest(),
                "chunk_count": len(records),
                "chunk_ids": [record["id"] for record in records],
            }
        )

    corpus_bytes = "".join(f"{_stable_json(record)}\n" for record in all_records).encode("utf-8")
    project_counts = Counter(record["metadata"]["project"] for record in all_records)
    source_type_counts = Counter(record["metadata"]["source_type"] for record in all_records)
    manifest = {
        "schema_version": 1,
        "pipeline_version": "kb-pipeline-v1",
        "chunking": {
            "algorithm": "markdown-section-estimated-token-v1",
            "max_tokens": max_tokens,
            "overlap_tokens": overlap_tokens,
        },
        "catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "logical_document_count": len(projection.documents),
        "chunk_count": len(all_records),
        "distributions": {
            "project": dict(sorted(project_counts.items())),
            "source_type": dict(sorted(source_type_counts.items())),
        },
        "documents": manifest_documents,
        "excluded": list(projection.excluded),
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    corpus_path = output / "corpus.jsonl"
    manifest_path = output / "manifest.json"
    _atomic_write(corpus_path, corpus_bytes)
    _atomic_write(manifest_path, manifest_bytes)
    return BuildResult(
        corpus_path=corpus_path,
        manifest_path=manifest_path,
        logical_document_count=len(projection.documents),
        chunk_count=len(all_records),
    )
