"""
ocr_client.py — 百度 OCR 客户端
==============================
扫描件 PDF 的 OCR 识别接口。
免费额度：通用文字识别（高精度版）1000次/天。

使用方式：
  百度云控制台 → 产品服务 → 文字识别 → 创建应用
  获取 API Key + Secret Key，填入 .env 即可。

  .env 配置：
    BAIDU_OCR_API_KEY=your-api-key
    BAIDU_OCR_SECRET_KEY=your-secret-key

用法：
  from ocr_client import OcrClient

  client = OcrClient()
  text = client.ocr_pdf(pdf_bytes)  # 全文 OCR
  # 或逐页：
  for page_text in client.ocr_pdf_pages(pdf_bytes):
      print(page_text)
"""

import base64
import io
import logging
import os
import time

logger = logging.getLogger(__name__)

BAIDU_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
BAIDU_OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic"


class OcrClient:
    """百度 OCR 客户端，支持单图和 PDF 识别"""

    def __init__(self, api_key: str = None, secret_key: str = None):
        self.api_key = api_key or os.environ.get("BAIDU_OCR_API_KEY", "")
        self.secret_key = secret_key or os.environ.get("BAIDU_OCR_SECRET_KEY", "")
        self._token = None
        self._token_expires_at = 0
        self._http = None

    # =============================================
    # Token 管理（自动缓存，过期刷新）
    # =============================================

    def _ensure_http(self):
        if self._http is None:
            self._http = httpx.Client(timeout=30)

    def _get_token(self) -> str:
        if time.time() < self._token_expires_at and self._token:
            return self._token
        if not self.api_key or not self.secret_key:
            raise ValueError(
                "百度 OCR 未配置。请在 .env 中设置 BAIDU_OCR_API_KEY 和 BAIDU_OCR_SECRET_KEY。"
            )
        self._ensure_http()
        resp = self._http.post(BAIDU_TOKEN_URL, params={
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        })
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"获取百度 token 失败: {data.get('error_description', data)}")
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 2592000) - 300
        logger.info("百度 OCR token 已刷新，有效期 30 天")
        return self._token

    # =============================================
    # 单页图片 OCR
    # =============================================

    def ocr_image(self, image_bytes: bytes) -> str:
        """识别一张图片，返回文本"""
        token = self._get_token()
        img_b64 = base64.b64encode(image_bytes).decode("ascii")
        self._ensure_http()
        resp = self._http.post(
            BAIDU_OCR_URL,
            params={"access_token": token},
            data={"image": img_b64},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = resp.json()
        if "words_result" not in data:
            error_msg = data.get("error_msg", str(data))
            logger.warning("百度 OCR 识别失败: %s", error_msg)
            return ""
        lines = [item["words"] for item in data["words_result"]]
        return "\n".join(lines)

    # =============================================
    # PDF 全文 OCR
    # =============================================

    def ocr_pdf(self, pdf_stream: bytes) -> str:
        """将 PDF 每页转为图片后 OCR，返回拼接文本"""
        import fitz
        doc = fitz.open(stream=pdf_stream, filetype="pdf")
        results = []
        total = len(doc)
        for i, page in enumerate(doc, 1):
            # 每页转为 PNG 图片（200 DPI）
            mat = fitz.Matrix(2, 2)  # 2x zoom = ~144 DPI，足够 OCR
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            text = self.ocr_image(img_bytes)
            if text:
                results.append(text)
            logger.info("OCR 第 %d/%d 页: %d 字", i, total, len(text))
        return "\n\n".join(results)

    def ocr_pdf_pages(self, pdf_stream: bytes) -> list[str]:
        """返回每页 OCR 结果列表，每页独立"""
        import fitz
        doc = fitz.open(stream=pdf_stream, filetype="pdf")
        pages = []
        for page in doc:
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            text = self.ocr_image(img_bytes)
            pages.append(text)
        return pages

    @property
    def is_configured(self) -> bool:
        """检查是否已配置百度 OCR 密钥"""
        return bool(self.api_key and self.secret_key)
