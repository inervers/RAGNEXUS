from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from kb_pipeline import (
    CatalogEntry,
    CatalogError,
    ProjectedDocument,
    ProjectedSection,
    build_artifacts,
    chunk_projected_document,
    estimate_tokens,
    load_catalog,
    make_chunk_id,
    normalize_text,
    project_catalog,
)


REQUIRED = {
    "doc_id": "ragnexus:incident:fixture:v1",
    "title": "Fixture",
    "project": "ragnexus",
    "source_type": "incident",
    "version": "v1",
    "commit": "abc1234",
    "updated_at": "2026-08-10",
    "authority": "project_truth",
    "source": "source.md",
    "status": "current",
    "sensitivity": "public",
    "sections": ["目标章节"],
}


def write_catalog(path: Path, entries: list[dict]) -> Path:
    path.write_text(
        json.dumps({"schema_version": 1, "documents": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_load_catalog_rejects_missing_required_metadata(tmp_path: Path) -> None:
    entry = dict(REQUIRED)
    del entry["commit"]
    catalog = write_catalog(tmp_path / "catalog.json", [entry])

    with pytest.raises(CatalogError, match="commit"):
        load_catalog(catalog)


def test_load_catalog_rejects_duplicate_logical_doc_id(tmp_path: Path) -> None:
    catalog = write_catalog(tmp_path / "catalog.json", [REQUIRED, REQUIRED])

    with pytest.raises(CatalogError, match="duplicate doc_id"):
        load_catalog(catalog)


def test_project_catalog_selects_exact_markdown_heading(tmp_path: Path) -> None:
    (tmp_path / "source.md").write_text(
        "# 文档标题\n\n> 人工 metadata\n\n## 目标章节\n\n事实 A。\n\n### 子章节\n\n事实 B。\n\n## 不应进入\n\n事实 C。\n",
        encoding="utf-8",
    )
    catalog = write_catalog(tmp_path / "catalog.json", [REQUIRED])

    result = project_catalog(catalog)

    assert len(result.documents) == 1
    document = result.documents[0]
    assert document.doc_id == REQUIRED["doc_id"]
    assert document.title == "Fixture"
    assert [section.path for section in document.sections] == ["目标章节"]
    assert "事实 A" in document.sections[0].text
    assert "### 子章节" in document.sections[0].text
    assert "事实 B" in document.sections[0].text
    assert "事实 C" not in document.sections[0].text
    assert len(document.source_sha256) == 64


def test_project_catalog_fails_when_declared_heading_is_missing(tmp_path: Path) -> None:
    (tmp_path / "source.md").write_text("# 文档\n\n## 其他章节\n\n内容\n", encoding="utf-8")
    catalog = write_catalog(tmp_path / "catalog.json", [REQUIRED])

    with pytest.raises(CatalogError, match="目标章节"):
        project_catalog(catalog)


def test_project_catalog_excludes_before_reading_non_public_source(tmp_path: Path) -> None:
    restricted = {
        **REQUIRED,
        "doc_id": "ragnexus:note:restricted:v1",
        "source": "does-not-exist.md",
        "status": "archived",
        "sensitivity": "restricted",
    }
    catalog = write_catalog(tmp_path / "catalog.json", [restricted])

    result = project_catalog(catalog)

    assert result.documents == ()
    assert result.excluded == (
        {
            "doc_id": "ragnexus:note:restricted:v1",
            "reason": "status=archived,sensitivity=restricted",
        },
    )


def test_repository_catalog_declares_ten_unique_logical_documents() -> None:
    catalog = Path(__file__).parents[1] / "kb_v2" / "catalog.json"

    entries = load_catalog(catalog)

    assert len(entries) == 10
    assert len({entry.doc_id for entry in entries}) == 10
    assert {entry.project for entry in entries} == {"ragnexus", "tradewind", "prism"}


def fixture_document(text: str, *, sections: tuple[ProjectedSection, ...] | None = None) -> ProjectedDocument:
    entry = CatalogEntry(
        **{key: value for key, value in REQUIRED.items() if key != "sections"},
        sections=tuple(REQUIRED["sections"]),
    )
    return ProjectedDocument(
        entry=entry,
        source_sha256="a" * 64,
        sections=sections or (ProjectedSection(path="目标章节", text=text),),
    )


def test_normalize_text_is_nfc_lf_and_preserves_code_spacing() -> None:
    raw = "Cafe\u0301  \r\n\r\n\r\n```python\r\nx  =  1\r\n```\r\n"

    normalized = normalize_text(raw)

    assert normalized == "Café\n\n```python\nx  =  1\n```"


def test_normalize_text_preserves_consecutive_blank_lines_inside_code_fence() -> None:
    raw = "前文\n\n\n```text\nline 1\n\n\nline 2\n```\n"

    normalized = normalize_text(raw)

    assert normalized == "前文\n\n```text\nline 1\n\n\nline 2\n```"


def test_estimate_tokens_counts_cjk_ascii_words_and_punctuation() -> None:
    assert estimate_tokens("你好 abcdefgh!") == 5


def test_make_chunk_id_is_content_addressed_and_ignores_position() -> None:
    first = make_chunk_id("ragnexus:incident:fixture:v1", "统一\r\n文本")
    second = make_chunk_id("ragnexus:incident:fixture:v1", "统一\n文本")

    assert first == second
    assert first.startswith("ragnexus:incident:fixture:v1#")
    assert len(first.rsplit("#", 1)[1]) == 16


def test_chunker_respects_budget_and_keeps_heading_context() -> None:
    document = fixture_document("第一句用于说明背景。第二句解释根因。第三句给出修复。第四句记录验证。")

    records = chunk_projected_document(document, max_tokens=28, overlap_tokens=4)

    assert len(records) >= 2
    assert [record["metadata"]["chunk_index"] for record in records] == list(range(len(records)))
    assert all(record["document"].startswith("# Fixture\n\n## 目标章节\n\n") for record in records)
    assert all(estimate_tokens(record["document"]) <= 28 for record in records)
    assert all(record["id"] == make_chunk_id(REQUIRED["doc_id"], record["document"]) for record in records)


def test_chunker_overlap_repeats_tail_context_without_duplicate_ids() -> None:
    document = fixture_document("甲甲甲甲。乙乙乙乙。丙丙丙丙。丁丁丁丁。戊戊戊戊。")

    records = chunk_projected_document(document, max_tokens=24, overlap_tokens=5)

    assert len(records) >= 2
    marker = "## 目标章节\n\n"
    first_body = records[0]["document"].split(marker, 1)[1]
    second_body = records[1]["document"].split(marker, 1)[1]
    assert first_body[-5:] in second_body
    assert len({record["id"] for record in records}) == len(records)


def test_chunker_rejects_duplicate_normalized_chunk_identity() -> None:
    duplicate_sections = (
        ProjectedSection(path="目标章节", text="完全相同。"),
        ProjectedSection(path="目标章节", text="完全相同。"),
    )
    document = fixture_document("unused", sections=duplicate_sections)

    with pytest.raises(CatalogError, match="duplicate chunk identity"):
        chunk_projected_document(document, max_tokens=40, overlap_tokens=5)


def test_chunker_hard_splits_oversized_ascii_atom() -> None:
    document = fixture_document("".join(f"{index:04d}" for index in range(60)))

    records = chunk_projected_document(document, max_tokens=25, overlap_tokens=3)

    assert len(records) >= 2
    assert all(estimate_tokens(item["document"]) <= 25 for item in records)


def test_build_artifacts_is_byte_stable_and_hashes_jsonl(tmp_path: Path) -> None:
    (tmp_path / "source.md").write_text(
        "# Source\n\n## 目标章节\n\n第一条事实。第二条事实。\n",
        encoding="utf-8",
    )
    catalog = write_catalog(tmp_path / "catalog.json", [REQUIRED])
    output = tmp_path / "build"

    first = build_artifacts(catalog, output, max_tokens=40, overlap_tokens=5)
    first_corpus = first.corpus_path.read_bytes()
    first_manifest = first.manifest_path.read_bytes()
    second = build_artifacts(catalog, output, max_tokens=40, overlap_tokens=5)

    assert second.corpus_path.read_bytes() == first_corpus
    assert second.manifest_path.read_bytes() == first_manifest
    manifest = json.loads(first_manifest)
    assert manifest["corpus_sha256"] == hashlib.sha256(first_corpus).hexdigest()
    assert manifest["logical_document_count"] == 1
    assert manifest["chunk_count"] == 1
    assert manifest["distributions"]["project"] == {"ragnexus": 1}
    assert manifest["documents"][0]["source_sha256"] == hashlib.sha256(
        (tmp_path / "source.md").read_bytes()
    ).hexdigest()


def test_build_artifacts_replaces_corrupt_outputs_atomically(tmp_path: Path) -> None:
    (tmp_path / "source.md").write_text("# Source\n\n## 目标章节\n\n可信事实。\n", encoding="utf-8")
    catalog = write_catalog(tmp_path / "catalog.json", [REQUIRED])
    output = tmp_path / "build"
    build_artifacts(catalog, output, max_tokens=40, overlap_tokens=5)
    (output / "corpus.jsonl").write_text("corrupt", encoding="utf-8")
    (output / "manifest.json").write_text("corrupt", encoding="utf-8")

    result = build_artifacts(catalog, output, max_tokens=40, overlap_tokens=5)

    assert result.chunk_count == 1
    assert json.loads(result.corpus_path.read_text(encoding="utf-8").splitlines()[0])["id"].startswith(
        REQUIRED["doc_id"] + "#"
    )
    assert json.loads(result.manifest_path.read_text(encoding="utf-8"))["chunk_count"] == 1


def test_repository_catalog_builds_ten_logical_documents(tmp_path: Path) -> None:
    catalog = Path(__file__).parents[1] / "kb_v2" / "catalog.json"

    result = build_artifacts(catalog, tmp_path / "build")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.logical_document_count == 10
    assert result.chunk_count > result.logical_document_count
    assert manifest["excluded"] == []
    assert set(manifest["distributions"]["project"]) == {"ragnexus", "tradewind", "prism"}
    build_artifacts,
