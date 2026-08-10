"""Download the exact MiniLM files needed by RAGNEXUS and verify SHA256."""

from __future__ import annotations

import argparse
import hashlib
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path


EXPECTED_FILES = {
    "config.json": "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41",  # pragma: allowlist secret -- public SHA256
    "model.safetensors": "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db",  # pragma: allowlist secret -- public SHA256
    "special_tokens_map.json": "303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3",  # pragma: allowlist secret -- public SHA256
    "tokenizer_config.json": "acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b",  # pragma: allowlist secret -- public SHA256
    "tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",  # pragma: allowlist secret -- public SHA256
    "vocab.txt": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",  # pragma: allowlist secret -- public SHA256
}


def _download(url: str, destination: Path, expected_sha256: str) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    downloaded = 0
    request = urllib.request.Request(url, headers={"User-Agent": "RAGNEXUS-build/1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if downloaded % (16 * 1024 * 1024) < len(chunk):
                    print(f"  downloaded {downloaded // (1024 * 1024)} MiB", flush=True)
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise ValueError(
                f"SHA256 mismatch for {destination.name}: expected {expected_sha256}, got {actual}"
            )
        os.replace(temporary, destination)
        print(f"verified {destination.name} ({downloaded} bytes)", flush=True)
    finally:
        if temporary.exists():
            temporary.unlink()


def download_snapshot(endpoint: str, repo: str, revision: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = endpoint.rstrip("/")
    quoted_revision = urllib.parse.quote(revision, safe="")
    for filename, expected_sha256 in EXPECTED_FILES.items():
        url = f"{base}/{repo}/resolve/{quoted_revision}/{filename}"
        last_error = None
        for attempt in range(1, 4):
            try:
                print(f"downloading {filename} (attempt {attempt}/3)", flush=True)
                _download(url, output_dir / filename, expected_sha256)
                break
            except Exception as exc:  # network boundary: retry then surface exact cause
                last_error = exc
                if attempt < 3:
                    time.sleep(attempt)
        else:
            raise RuntimeError(f"failed to download {filename}: {last_error}") from last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    download_snapshot(args.endpoint, args.repo, args.revision, args.output)


if __name__ == "__main__":
    main()
