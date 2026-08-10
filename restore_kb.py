"""从 demo_docs/ 重新导入知识库。

用途：恢复被清空的 chroma_db（2026-08-02 发现知识库从 718 块变为 0，后端自动初始化了 7 块示例）。
用法：
    1. 先启动后端：python rag_api.py
    2. 再执行：python restore_kb.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from security_config import load_api_key

ROOT = Path(__file__).resolve().parent
API_ROOT = os.environ.get("RAG_API_ROOT", "http://localhost:8000")
API_KEY = load_api_key(os.environ)
DOCS_DIR = ROOT / "demo_docs"


def post(path: str, payload: dict) -> dict:
    req = Request(
        API_ROOT + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    if not DOCS_DIR.exists():
        print(f"✗ 找不到目录：{DOCS_DIR}")
        return

    files = sorted(f for f in os.listdir(DOCS_DIR) if f.endswith(".txt"))
    if not files:
        print("✗ demo_docs/ 下没有 txt 文档")
        return

    total_chunks = 0
    for fn in files:
        title = fn[:-4]
        content = (DOCS_DIR / fn).read_text(encoding="utf-8")
        try:
            result = post("/doc", {"title": title, "content": content})
            msg = result.get("message", "")
            print(f"✓ {fn}  →  {msg}")
            total_chunks += 1
        except Exception as exc:
            print(f"✗ {fn} 导入失败: {exc}")

    print(f"\n完成：{len(files)} 个文档已导入（每个文档含多个分块）")


if __name__ == "__main__":
    main()
