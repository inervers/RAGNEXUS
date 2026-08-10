"""Pure document parsing and import helpers shared by preview and formal import."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass


class DocumentIngestError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    text: str


def parse_uploaded_document(filename: str, encoded_content: str) -> ParsedDocument:
    clean_filename = filename.strip()
    if not clean_filename or not encoded_content.strip():
        raise DocumentIngestError("文件名和内容不能为空")

    try:
        raw_bytes = base64.b64decode(encoded_content, validate=True)
    except (binascii.Error, ValueError):
        raise DocumentIngestError("Base64 解码失败") from None

    ext = clean_filename.rsplit(".", 1)[-1].lower() if "." in clean_filename else ""
    title = clean_filename.rsplit(".", 1)[0]
    if ext == "txt":
        return ParsedDocument(title=title, text=raw_bytes.decode("utf-8", errors="replace"))
    if ext == "pdf":
        try:
            from pdf_parser import extract_text

            parsed = extract_text(raw_bytes)
            return ParsedDocument(title=title, text=parsed["text"])
        except Exception as error:
            raise DocumentIngestError(
                f"PDF 解析失败：{error}", status_code=500
            ) from error
    raise DocumentIngestError(f"不支持的文件格式：.{ext}（仅支持 pdf/txt）")


def build_preview(parsed: ParsedDocument, limit: int = 5000) -> dict:
    return {
        "title": parsed.title,
        "preview": parsed.text[:limit],
        "full_length": len(parsed.text),
        "truncated": len(parsed.text) > limit,
    }


def import_uploaded_document(
    filename: str,
    encoded_content: str,
    add_document: Callable[[str, str], dict],
) -> dict:
    parsed = parse_uploaded_document(filename, encoded_content)
    result = add_document(parsed.title, parsed.text)
    return {
        "title": parsed.title,
        "parsed_length": len(parsed.text),
        **result,
    }
