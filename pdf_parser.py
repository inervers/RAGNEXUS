"""
pdf_parser.py — PDF 多层解析模块
================================
第①层：文字提取 + 表格结构还原
第②层：扫描件检测 + OCR 预留接口

依赖：
  - PyMuPDF (fitz) → 文字提取、页数、元数据
  - pdfplumber  → 表格提取（保留行列结构）

用法：
  from pdf_parser import parse_pdf
  result = parse_pdf(pdf_bytes)
  # result = {
  #   "text": str,          # 全部文本
  #   "pages": int,         # 总页数
  #   "chars": int,         # 文本长度
  #   "is_scanned": bool,   # 是否扫描件
  #   "tables": [...],      # 表格列表
  #   "has_tables": bool,   # 是否有表格
  # }
"""

import io
import logging

logger = logging.getLogger(__name__)

# =============================================
# 检测
# =============================================

def _get_fitz_text(pdf_stream: bytes) -> tuple[int, str]:
    """用 PyMuPDF 提取文本，返回 (字符数, 文本)"""
    import fitz
    doc = fitz.open(stream=pdf_stream, filetype="pdf")
    pages_text = []
    for page in doc:
        t = page.get_text().strip()
        if t:
            pages_text.append(t)
    full = "\n".join(pages_text)
    return len(full), full


def is_scanned(pdf_stream: bytes) -> tuple[bool, int]:
    """
    检测 PDF 是否为扫描件（无文字层）。
    返回 (是否扫描件, 提取到的字符数)
    """
    try:
        chars, _ = _get_fitz_text(pdf_stream)
        return chars == 0, chars
    except Exception as e:
        logger.warning("PDF 解析异常: %s", e)
        return True, 0


# =============================================
# 文本提取
# =============================================

def extract_text(pdf_stream: bytes) -> dict:
    """提取 PDF 全文文本，返回 {text, pages, chars, is_scanned}"""
    import fitz
    doc = fitz.open(stream=pdf_stream, filetype="pdf")
    page_count = len(doc)
    pages_text = []
    for page in doc:
        t = page.get_text().strip()
        if t:
            pages_text.append(t)
    full = "\n".join(pages_text)
    return {
        "text": full,
        "pages": page_count,
        "chars": len(full),
        "is_scanned": len(full) == 0,
    }


# =============================================
# 表格提取（pdfplumber）
# =============================================

def extract_tables(pdf_stream: bytes) -> list[dict]:
    """
    提取 PDF 中的表格。
    返回 [{page, table_index, markdown, rows, cols}]
    空列表 = 无表格

    依赖 pdfplumber，未安装时返回空。
    """
    try:
        import pdfplumber
    except ImportError:
        logger.debug("pdfplumber 未安装，跳过表格提取")
        return []

    try:
        tables_found = []
        with pdfplumber.open(io.BytesIO(pdf_stream)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                raw_tables = page.extract_tables()
                for ti, table in enumerate(raw_tables):
                    if not table or len(table) < 2:
                        continue
                    # 过滤全空行
                    clean = []
                    for row in table:
                        cells = [c.strip() if c else "" for c in row]
                        if any(c for c in cells):
                            clean.append(cells)
                    if len(clean) < 2:
                        continue

                    md = _to_markdown(clean)
                    tables_found.append({
                        "page": page_num,
                        "table_index": ti,
                        "markdown": md,
                        "rows": len(clean),
                        "cols": len(clean[0]) if clean[0] else 0,
                    })
        return tables_found
    except Exception as e:
        logger.warning("表格提取失败: %s", e)
        return []


def _to_markdown(table: list[list[str]]) -> str:
    """二维表 → Markdown"""
    lines = []
    for ri, row in enumerate(table):
        line = "| " + " | ".join(row) + " |"
        lines.append(line)
        if ri == 0:
            sep = "| " + " | ".join("---" for _ in row) + " |"
            lines.append(sep)
    return "\n".join(lines)


# =============================================
# 完整解析
# =============================================

def parse_pdf(pdf_stream: bytes) -> dict:
    """
    完整解析 PDF，返回结构化的解析结果。

    返回:
      text        — 全文文本
      pages       — 总页数
      chars       — 文本长度
      is_scanned  — 是否扫描件
      tables      — 表格列表 [{page, markdown, rows, cols}]
      has_tables  — 是否有表格
      summary     — 一句话摘要，如 "6页 · 3个表格 · 4200字"

    注意：
      - 扫描件 is_scanned=True，text 为空字符串
      - 表格以 Markdown 格式存入 tables[].markdown
      - text 中不包含表格内容，表格单独在 tables 里
    """
    base = extract_text(pdf_stream)
    tables = extract_tables(pdf_stream)

    base["tables"] = tables
    base["has_tables"] = len(tables) > 0

    parts = []
    parts.append(f"{base['pages']}页")
    if tables:
        parts.append(f"{len(tables)}个表格")
    if base['chars'] > 0:
        parts.append(f"{base['chars']}字")
    else:
        parts.append("扫描件")
    base["summary"] = " · ".join(parts)

    return base


# =============================================
# Layer 2：OCR 集成
# =============================================

def _try_ocr(pdf_stream: bytes) -> str | None:
    """
    如果配置了百度 OCR，对扫描件执行识别。
    返回识别文本，未配置时返回 None。
    """
    try:
        from ocr_client import OcrClient
        client = OcrClient()
        if not client.is_configured:
            logger.info("百度 OCR 未配置，跳过扫描件识别")
            return None
        logger.info("百度 OCR 已配置，开始识别扫描件...")
        text = client.ocr_pdf(pdf_stream)
        logger.info("OCR 完成: %d 字", len(text))
        return text
    except ImportError:
        logger.debug("ocr_client 模块未安装")
        return None
    except Exception as e:
        logger.warning("OCR 识别异常: %s", e)
        return None


def parse_pdf_with_ocr(pdf_stream: bytes) -> dict:
    """
    解析 PDF，扫描件自动触发 OCR 兜底。
    返回格式与 parse_pdf() 完全一致。
    """
    result = parse_pdf(pdf_stream)
    if result["is_scanned"]:
        ocr_text = _try_ocr(pdf_stream)
        if ocr_text:
            result["text"] = ocr_text
            result["chars"] = len(ocr_text)
            result["is_scanned"] = False  # OCR 后视为已处理
            result["summary"] = f"{result['pages']}页 · OCR 识别 · {len(ocr_text)}字"
            result["ocr_used"] = True
        else:
            result["ocr_used"] = False
    else:
        result["ocr_used"] = False
    return result
