# -*- coding: utf-8 -*-
"""清理知识库垃圾块：Agent 笔记导入时带进来的 CSS 样式块 + hello world 测试块。

背景（2026-08-03 评测发现）：
- 负样本题"markdown-body 的 CSS 样式规则"三路检索全部 0.8 命中，证实 CSS 块污染检索。
- doc_393-415 共 23 块是 .markdown-body / hljs 样式定义（HTML 导出残留），非正文。
- doc_1223 是 "hello world" 测试块。

判定规则（内容特征，不依赖 source）：
- 含 ".markdown-body" 或 "hljs-" → CSS 样式块
- source == "test" → 测试垃圾块

用法（容器停止状态下执行，本地与容器共享 bind mount chroma_db）:
    python clean_css_junk.py
"""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rag_api  # 复用同一 client/collection 配置（不启动服务）

col = rag_api.collection

before = col.count()
print(f"=== BEFORE: {before} chunks ===")

data = col.get(include=["documents", "metadatas"])
ids, docs, metas = data["ids"], data["documents"], data["metadatas"]

CSS_MARKERS = (".markdown-body", "hljs-")

to_delete = []
kept_mixed = []
for i, (cid, doc, meta) in enumerate(zip(ids, docs, metas)):
    src = (meta or {}).get("source", "?")
    is_css = any(m in doc for m in CSS_MARKERS)
    if is_css:
        to_delete.append(cid)
        print(f"  [CSS] {cid}  source={src}  内容: {doc[:60]}...")
    elif src == "test":
        to_delete.append(cid)
        print(f"  [TEST] {cid}  source={src}  内容: {doc[:60]}...")

print(f"\n待删除: {len(to_delete)} 块")
if not to_delete:
    print("没有需要清理的块，结束。")
    sys.exit(0)

# 删除（ChromaDB 1.5.9 delete 返回值不可信，以 count 差值为准）
col.delete(ids=to_delete)
after = col.count()
print(f"=== AFTER: {after} chunks (removed {before - after}) ===")

# 剩余来源分布，供复查
data2 = col.get(include=["metadatas"])
dist = Counter(m.get("source", "?") for m in data2["metadatas"])
print("--- remaining source distribution ---")
for s, c in dist.most_common():
    print(f"  {c:>4}  {s}")
