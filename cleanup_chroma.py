# -*- coding: utf-8 -*-
"""清理知识库垃圾数据（torch.Tensor 坏块 / license 误导入 / langchain 英文测试语料）。

用法（在 rag-agent-api 项目根目录，后端停止状态下执行）:
    python cleanup_chroma.py

复用 rag_api 的 collection 连接，保证与正式服务同一 ChromaDB 实例。
"""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rag_api  # 复用同一 client/collection 配置（不启动服务）

col = rag_api.collection

# 删除名单（metadata.source 精确匹配）
DROP_SOURCES = [
    # 第一轮：导入 bug 产物 + 误导入 + 前 15 名测试语料
    "torch.Tensor",                                        # 导入 bug 产物，坏块
    "license",                                             # 误导入的许可证文本
    "The Black Maria",                                     # langchain 测试语料
    "You can't bury them all: Poems",                      # langchain 测试语料
    "Sharp Objects",                                       # langchain 测试语料
    "Mesaerion: The Best Science Fiction Stories 1800-1849",
    "Olio",
    "How Music Works",
    "Sophie's World",
    # 第二轮：前 15 名之外的测试语料（LangChain/ChromaDB fixtures）
    "It's Only the Himalayas",
    "Black Dust",
    "Our Band Could Be Your Life: Scenes from the American Indie Underground, 1981-1991",
    "Libertarianism for Beginners",
    "Soumission",
    "Rip it Up and Start Again",
    "Scott Pilgrim's Precious Little Life (Scott Pilgrim #1)",
    "The Requiem Red",
    "Tipping the Velvet",
    "A Light in the Attic",
    "In Her Wake",
    "The Elephant Tree",
    "Behind Closed Doors",
    "The Bear and the Piano",
    "All products",
    "Set Me Free",
    "Shakespeare's Sonnets",
    "Wall and Piece",
    "In a Dark, Dark Wood",
    "Penny Maybe",
]

before = col.count()
print(f"=== BEFORE: {before} chunks ===")

for src in DROP_SOURCES:
    try:
        n = col.delete(where={"source": src})
        print(f"  deleted [{src}]: {len(n) if n else 0}")
    except Exception as e:
        print(f"  FAIL [{src}]: {e}")

after = col.count()
print(f"=== AFTER: {after} chunks (removed {before - after}) ===")

# 剩余来源分布，供人工复查
data = col.get(include=["metadatas"])
dist = Counter(m.get("source", "?") for m in data["metadatas"])
print("--- remaining source distribution ---")
for s, c in dist.most_common():
    print(f"  {c:>4}  {s}")
