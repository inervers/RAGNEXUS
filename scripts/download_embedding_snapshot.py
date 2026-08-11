"""Download the exact MiniLM files needed by RAGNEXUS and verify SHA256."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DownloadManifest:
    model_id: str
    revision: str
    files: dict[str, dict[str, int | str]]


def load_download_manifest(manifest_path: str | Path) -> DownloadManifest:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    model_id = manifest.get("model_id")
    revision = manifest.get("revision")
    raw_files = manifest.get("files")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("manifest model_id must be a non-empty string")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("manifest revision must be a non-empty string")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("manifest files must be a non-empty list")
    files: dict[str, dict[str, int | str]] = {}
    for item in raw_files:
        relative = Path(item.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"unsafe manifest path: {relative}")
        filename = relative.as_posix()
        if filename in files:
            raise ValueError(f"duplicate manifest path: {filename}")
        size = item.get("size")
        digest = item.get("sha256")
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"invalid size for {filename}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"invalid SHA256 for {filename}")
        files[filename] = {"size": size, "sha256": digest}
    return DownloadManifest(model_id, revision, files)


def _download(
    url: str,
    destination: Path,
    expected_sha256: str,
    expected_size: int | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
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
        if expected_size is not None and downloaded != expected_size:
            raise ValueError(
                f"size mismatch for {destination.name}: expected {expected_size}, got {downloaded}"
            )
        if actual != expected_sha256:
            raise ValueError(
                f"SHA256 mismatch for {destination.name}: expected {expected_sha256}, got {actual}"
            )
        os.replace(temporary, destination)
        print(f"verified {destination.name} ({downloaded} bytes)", flush=True)
    finally:
        if temporary.exists():
            temporary.unlink()


def download_snapshot(
    endpoint: str, manifest_path: str | Path, output_dir: Path
) -> None:
    manifest = load_download_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = endpoint.rstrip("/")
    quoted_revision = urllib.parse.quote(manifest.revision, safe="")
    for filename, expected in manifest.files.items():
        quoted_filename = urllib.parse.quote(filename, safe="/")
        url = f"{base}/{manifest.model_id}/resolve/{quoted_revision}/{quoted_filename}"
        last_error = None
        for attempt in range(1, 4):
            try:
                print(f"downloading {filename} (attempt {attempt}/3)", flush=True)
                _download(
                    url,
                    output_dir / filename,
                    str(expected["sha256"]),
                    int(expected["size"]),
                )
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
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    download_snapshot(args.endpoint, args.manifest, args.output)


if __name__ == "__main__":
    main()
