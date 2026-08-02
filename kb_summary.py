#!/usr/bin/env python3
"""把 kb_export json 转成人工可读摘要，供评测集编写使用。"""
import json
from collections import defaultdict

SRC = "kb_export_20260802.json"
OUT = "kb_summary.txt"

with open(SRC, encoding="utf-8") as f:
    data = json.load(f)

ids, docs, metas = data["ids"], data["documents"], data["metadatas"]
groups = defaultdict(list)
for i, (cid, doc, meta) in enumerate(zip(ids, docs, metas)):
    src = (meta or {}).get("source", "unknown")
    groups[src].append((cid, doc))

lines = []
lines.append(f"总块数: {len(ids)}")
lines.append("=" * 70)
for src, items in sorted(groups.items(), key=lambda x: -len(x[1])):
    lines.append(f"\n## {src} ({len(items)} 块)")
    for cid, doc in items:
        # 单行压缩：换行变空格，截前 220 字
        flat = " ".join(doc.split())
        lines.append(f"[{cid}] {flat[:220]}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"OK -> {OUT}  ({sum(len(v) for v in groups.values())} 块, {len(groups)} 个来源)")
