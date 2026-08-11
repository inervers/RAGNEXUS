# DOCX Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe `.docx` preview and full import with ordered paragraph/table extraction and a unified 25 MB upload limit.

**Architecture:** Keep `document_ingest.py` as the format-dispatch boundary and add a focused `python-docx` parser for top-level body blocks. Reuse the existing Base64, preview, and fail-before-write flow; update the existing frontend validation helper and upload copy without changing API contracts.

**Tech Stack:** Python 3.11, python-docx, FastAPI helpers, pytest, React 19, TypeScript, Node test runner, Docker.

## Global Constraints

- Support `.docx` only; do not add `.doc`, `.docm`, OCR, comments, headers, or footers.
- Use a decoded-file limit of exactly `25 * 1024 * 1024` bytes for PDF, TXT, and DOCX.
- Preserve preview limit 5,000 characters and reparse the original payload for formal import.
- Invalid or empty DOCX input must fail before the knowledge-base callback runs.
- Preserve unrelated untracked files `.agents/`, `docs/EVAL.md`, and `kb_summary.txt`.

---

### Task 1: Backend DOCX parser and limits

**Files:**
- Modify: `tests/test_document_ingest_unit.py`
- Modify: `document_ingest.py`
- Modify: `requirements-api.txt`

**Interfaces:**
- Consumes: `parse_uploaded_document(filename: str, encoded_content: str, *, max_bytes: int = MAX_UPLOAD_BYTES)`.
- Produces: `.docx` support returning the existing `ParsedDocument`; `MAX_UPLOAD_BYTES = 25 * 1024 * 1024`.

- [ ] **Step 1: Write failing backend tests**

Add a DOCX fixture builder using `docx.Document` and `io.BytesIO`, then add tests asserting paragraph order, table-cell extraction, corrupt-DOCX error text, empty-DOCX fail-before-write, full-import completeness, and `MAX_UPLOAD_BYTES == 25 * 1024 * 1024`.

```python
def _encoded_docx(paragraphs=(), table_rows=()):
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    if table_rows:
        table = doc.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for row_index, row in enumerate(table_rows):
            for col_index, text in enumerate(row):
                table.cell(row_index, col_index).text = text
    stream = io.BytesIO()
    doc.save(stream)
    return base64.b64encode(stream.getvalue()).decode("ascii")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_document_ingest_unit.py -q`

Expected: DOCX cases fail with the existing `仅支持 pdf/txt` error and the limit assertion reports 10 MB instead of 25 MB.

- [ ] **Step 3: Implement minimal parser**

Pin `python-docx==1.2.0`. In `document_ingest.py`, parse `BytesIO(raw_bytes)` with `Document`, traverse `document.element.body.iterchildren()`, convert `CT_P` with `Paragraph` and `CT_Tbl` with `Table`, collect non-empty paragraph/cell text in source order, and wrap package/encryption/parser failures as `DocumentIngestError("DOCX 解析失败：文件损坏、加密或格式不受支持")`. Update unsupported-format copy to `pdf/txt/docx` and the default limit to 25 MB.

- [ ] **Step 4: Run backend tests and verify GREEN**

Run: `python -m pytest tests/test_document_ingest_unit.py -q`

Expected: all document-ingest tests pass.

### Task 2: Frontend selection and visible format guidance

**Files:**
- Modify: `frontend/tests/documentImport.test.ts`
- Modify: `frontend/src/documentImport.ts`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: browser `File` metadata and existing preview/import API calls.
- Produces: `.docx` acceptance, 25 MiB validation copy, and visible supported-format guidance.

- [ ] **Step 1: Write failing frontend tests**

Update the validation test to assert:

```typescript
assert.equal(validateSelectedFile({ name: "report.docx", size: 1024 }), null)
assert.equal(validateSelectedFile({ name: "notes.md", size: 12 }), "仅支持 PDF/TXT/DOCX 文件")
assert.match(validateSelectedFile({ name: "large.docx", size: 25 * 1024 * 1024 + 1 }) ?? "", /25 MiB/)
```

Add a source-contract assertion that `App.tsx` contains `accept=".pdf,.txt,.docx"` and `支持 PDF / UTF-8 TXT / DOCX，最大 25 MB`.

- [ ] **Step 2: Run tests and verify RED**

Run: `npm test -- documentImport.test.ts`

Expected: `.docx` is rejected and the old 10 MiB/PDF-TXT copy remains.

- [ ] **Step 3: Implement minimal frontend change**

Set `MAX_UPLOAD_BYTES = 25 * 1024 * 1024`, accept `pdf`, `txt`, and `docx`, update validation messages, change the input accept attribute, and add the visible hint without changing preview/import state handling.

- [ ] **Step 4: Run frontend tests and type-check**

Run: `npm test`

Run: `npm run build:check`

Expected: all frontend tests and TypeScript checks pass.

### Task 3: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-11-docx-import-design.md`

**Interfaces:**
- Consumes: implemented backend/frontend behavior.
- Produces: user-facing supported-format and 25 MB limit documentation.

- [ ] **Step 1: Update documentation**

Document `PDF / UTF-8 TXT / DOCX` support, the 25 MB decoded-file limit, and the `.docx` boundary excluding `.doc`, OCR, headers, footers, and comments.

- [ ] **Step 2: Run full regression suites**

Run: `python -m pytest -q`

Run: `npm test` from `frontend/`.

Run: `npm run build:check` from `frontend/`.

Expected: backend, frontend, and TypeScript suites pass with zero failures.

- [ ] **Step 3: Rebuild and smoke the Docker path**

Run: `docker compose build rag-api rag-frontend`

Run: `docker compose up -d --force-recreate`

Verify `/health` reports `status=ok`, `chunks=184`, and `embedding_pooling=masked_mean`; verify the served frontend bundle contains `.pdf,.txt,.docx`; perform one DOCX preview/import against an isolated temporary knowledge-base directory so the production 184-chunk database is not mutated.

- [ ] **Step 4: Commit the implementation**

Stage only the files listed in this plan and commit with `feat: support docx knowledge imports`. Do not push without an explicit user request.
