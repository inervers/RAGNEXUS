import base64

import pytest

from document_ingest import (
    DocumentIngestError,
    build_preview,
    import_uploaded_document,
    parse_uploaded_document,
)


def test_preview_truncation_never_changes_import_source() -> None:
    text = "知" * 6001
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")

    parsed = parse_uploaded_document("long.txt", encoded)
    preview = build_preview(parsed)

    assert preview == {
        "title": "long",
        "preview": "知" * 5000,
        "full_length": 6001,
        "truncated": True,
    }
    assert parsed.text == text


def test_formal_import_passes_all_parsed_text_to_kb_consumer() -> None:
    text = "完整内容" * 1501
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    received: list[tuple[str, str]] = []

    def add_document(title: str, content: str) -> dict:
        received.append((title, content))
        return {"message": "added", "chunks": 31}

    result = import_uploaded_document("full.txt", encoded, add_document)

    assert received == [("full", text)]
    assert result == {
        "title": "full",
        "parsed_length": len(text),
        "message": "added",
        "chunks": 31,
    }


def test_upload_rejects_decoded_content_over_limit() -> None:
    encoded = base64.b64encode(b"12345").decode("ascii")

    with pytest.raises(DocumentIngestError, match="超过"):
        parse_uploaded_document("large.txt", encoded, max_bytes=4)


def test_txt_rejects_invalid_utf8_instead_of_replacing_bytes() -> None:
    encoded = base64.b64encode(b"valid\xffinvalid").decode("ascii")

    with pytest.raises(DocumentIngestError, match="UTF-8"):
        parse_uploaded_document("invalid.txt", encoded)


def test_import_rejects_whitespace_only_text_before_kb_mutation() -> None:
    encoded = base64.b64encode(" \n\t".encode("utf-8")).decode("ascii")
    called = False

    def add_document(title: str, content: str) -> dict:
        nonlocal called
        called = True
        return {}

    with pytest.raises(DocumentIngestError, match="有效文本"):
        import_uploaded_document("empty.txt", encoded, add_document)

    assert called is False
