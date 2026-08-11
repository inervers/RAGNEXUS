# DOCX Import Design

## Goal

Extend the existing knowledge-base file import flow to accept modern Word `.docx` files alongside PDF and UTF-8 TXT, while preserving the current preview/import separation, upload-size limit, and fail-before-write behavior.

## Scope

- Support `.docx` only; legacy `.doc`, `.docm`, OCR, comments, headers, and footers remain unsupported.
- Raise the decoded-upload limit from 10 MB to 25 MB for PDF, UTF-8 TXT, and DOCX, while preserving meaningful-text validation.
- Preserve the current API request and response contracts for preview and full import.
- Update the frontend picker and visible copy to advertise PDF, UTF-8 TXT, and DOCX.

## Architecture

`document_ingest.parse_uploaded_document()` remains the single format-dispatch boundary. For `.docx`, it will pass the decoded bytes to a focused helper backed by `python-docx`. The helper will traverse top-level body blocks in document order, extracting normal paragraphs and table-cell paragraphs, then join non-empty blocks with newlines.

The preview route continues to return at most 5,000 characters, while formal import reparses the original Base64 payload and sends the complete extracted text to the existing `add_document` callback. Parsing must finish successfully before any knowledge-base write occurs.

## Error Handling

- A malformed, encrypted, or otherwise unreadable `.docx` returns `DocumentIngestError` with HTTP 400 semantics and a DOCX-specific message.
- A structurally valid document with no meaningful paragraph or table text returns the existing empty-document error.
- Files larger than 25 MB return HTTP 413 before parsing.
- Unsupported extensions continue to return HTTP 400, with the supported-format message updated to `pdf/txt/docx`.

## Frontend

- Change the hidden file input to `accept=".pdf,.txt,.docx"`.
- Add visible text in the upload zone: `支持 PDF / UTF-8 TXT / DOCX，最大 25 MB`.
- Keep drag-and-drop, preview, progress, and full-import behavior unchanged.

## Dependency

Add a pinned `python-docx` dependency to the API runtime requirements. Do not add LibreOffice or a legacy `.doc` conversion path.

## Testing

Backend tests must cover:

1. A DOCX containing normal paragraphs is decoded in order.
2. A DOCX containing a table includes table-cell text in document order.
3. A corrupt DOCX fails with a user-facing DOCX parse error.
4. An empty DOCX is rejected before `add_document` is called.
5. Full import passes the complete extracted DOCX text to the existing callback.

Frontend tests must verify that the picker accepts `.docx` and the visible hint lists DOCX. Existing TXT/PDF and long-document tests remain regression coverage.

## Acceptance Criteria

- A valid `.docx` can be selected or dragged into the UI, previewed, and fully imported.
- Paragraph and table text are present in the resulting knowledge-base input in source order.
- Invalid or empty DOCX files never modify the knowledge base.
- Backend tests, frontend tests, TypeScript `build:check`, and the relevant Docker smoke remain green.
