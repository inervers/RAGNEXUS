#!/usr/bin/env python3
"""Build deterministic RAGNEXUS V2 corpus artifacts without touching Chroma."""

from __future__ import annotations

import argparse

from kb_pipeline import build_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="kb_v2/catalog.json")
    parser.add_argument("--output", default="kb_v2/build")
    parser.add_argument("--max-tokens", type=int, default=220)
    parser.add_argument("--overlap-tokens", type=int, default=30)
    args = parser.parse_args()
    result = build_artifacts(
        args.catalog,
        args.output,
        max_tokens=args.max_tokens,
        overlap_tokens=args.overlap_tokens,
    )
    print(f"logical_documents={result.logical_document_count}")
    print(f"chunks={result.chunk_count}")
    print(f"corpus={result.corpus_path}")
    print(f"manifest={result.manifest_path}")


if __name__ == "__main__":
    main()
