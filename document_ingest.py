"""Pure document parsing and import helpers shared by preview and formal import."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class DocumentIngestError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    text: str


def _require_meaningful_text(parsed: ParsedDocument) -> ParsedDocument:
    if not parsed.text.strip():
        raise DocumentIngestError("文档没有可导入的有效文本")
    return parsed


def parse_uploaded_document(
    filename: str,
    encoded_content: str,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> ParsedDocument:
    clean_filename = filename.strip()
    encoded = encoded_content.strip()
    if not clean_filename or not encoded:
        raise DocumentIngestError("文件名和内容不能为空")
    max_encoded_length = 4 * ((max_bytes + 2) // 3)
    if len(encoded) > max_encoded_length:
        raise DocumentIngestError(f"文件超过 {max_bytes} 字节限制", status_code=413)

    try:
        raw_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise DocumentIngestError("Base64 解码失败") from None
    if len(raw_bytes) > max_bytes:
        raise DocumentIngestError(f"文件超过 {max_bytes} 字节限制", status_code=413)

    ext = clean_filename.rsplit(".", 1)[-1].lower() if "." in clean_filename else ""
    title = clean_filename.rsplit(".", 1)[0]
    if ext == "txt":
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise DocumentIngestError("TXT 文件必须使用有效 UTF-8 编码") from None
        return _require_meaningful_text(ParsedDocument(title=title, text=text))
    if ext == "pdf":
        try:
            from pdf_parser import extract_text

            parsed = extract_text(raw_bytes)
            return _require_meaningful_text(
                ParsedDocument(title=title, text=parsed["text"])
            )
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
