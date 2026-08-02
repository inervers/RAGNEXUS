#!/usr/bin/env python3
"""ChromaDB 0.5.17 → 1.5.9 数据迁移工具（2026-08-02）

背景：容器固定 chromadb==0.5.17，本地是 1.5.9。1.5.9 读 0.5.17 写的库报
`mismatched types; Rust type u64 (as SQL type INTEGER) is not compatible with SQL type BLOB`
（metadata 独立表 schema 不兼容，数据本身没坏）。统一升级到 1.5.9 后双环境共用。

用法（旧容器导出 / 新容器导入，同一脚本两边可跑）：
  export: python migrate_chroma.py export <db_path> <out.json>
  import: python migrate_chroma.py import <db_path> <in.json>

embedding 与 rag_api.py 完全一致：MiniLM-L6-v2 + mean pooling + L2 归一化，
导入时重新计算，检索向量空间不变。
"""
import argparse
import json

import chromadb
import torch
from transformers import AutoTokenizer, AutoModel

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_tok = None
_model = None


def _ensure_model():
    """懒加载：export 模式不碰模型，import 才加载。"""
    global _tok, _model
    if _tok is None:
        _tok = AutoTokenizer.from_pretrained(MODEL_NAME, local_files_only=True)
        _model = AutoModel.from_pretrained(MODEL_NAME, local_files_only=True)
    return _tok, _model


def _embed(texts):
    tok, model = _ensure_model()
    inputs = tok(texts, truncation=True, padding=True, return_tensors="pt", max_length=256)
    with torch.no_grad():
        pooled = model(**inputs).last_hidden_state.mean(dim=1)
    return (pooled / torch.norm(pooled, dim=1, keepdim=True)).numpy()


class MiniLMEmbedding(chromadb.api.types.EmbeddingFunction):
    """与 rag_api.py 同款 EF，兼容 0.5.17（不检查 name）与 1.5.9（需要 name/__init__）。"""

    def __init__(self):
        pass

    def __call__(self, input):
        if isinstance(input, (list, tuple)):
            texts = [d.text if hasattr(d, "text") else d for d in input]
        else:
            texts = [input]
        return [e.tolist() for e in _embed(texts)]

    def name(self):
        return "MiniLM-L6-v2-mean-pooling"


def main():
    parser = argparse.ArgumentParser(description="ChromaDB 数据迁移 0.5.17 → 1.5.9")
    parser.add_argument("mode", choices=["export", "import"])
    parser.add_argument("db_path", help="chroma_db 目录路径")
    parser.add_argument("json_path", help="导出/导入的 JSON 文件路径")
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=args.db_path)
    col = client.get_collection("rag_knowledge", embedding_function=MiniLMEmbedding())

    if args.mode == "export":
        data = col.get(include=["documents", "metadatas"])
        payload = {
            "ids": data["ids"],
            "documents": data["documents"],
            "metadatas": data["metadatas"],
        }
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        print(f"EXPORTED {len(payload['ids'])} chunks -> {args.json_path}")
    else:
        with open(args.json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        # 全量替换：先清空新库（避免与新库启动时的 init 块 id 冲突 doc_1..）
        existing = col.get()["ids"]
        if existing:
            col.delete(ids=existing)
            print(f"CLEARED {len(existing)} existing chunks")
        col.add(ids=payload["ids"], documents=payload["documents"], metadatas=payload["metadatas"])
        print(f"IMPORTED {col.count()} chunks into {args.db_path}")


if __name__ == "__main__":
    main()
