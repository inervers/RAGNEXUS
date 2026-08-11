from pathlib import Path
import hashlib

import pytest

from embedding_runtime import resolve_embedding_runtime_config
from scripts.download_embedding_snapshot import _download, load_download_manifest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_default_dockerfile_is_independent_of_personal_build_assets():
    dockerfile = _read("Dockerfile")

    assert "FROM python:3.11-slim" in dockerfile
    assert "ragnxus-rag-api" not in dockerfile
    assert ".wheels" not in dockerfile
    assert "requirements-api.txt" in dockerfile
    assert "paraphrase-multilingual-MiniLM-L12-v2.json" in dockerfile
    assert "e8f8c211226b894fcb81acc59f3b34ba3efd5f42" in dockerfile  # pragma: allowlist secret -- public model revision
    assert "RAG_EMBEDDING_POOLING=masked_mean" in dockerfile


def test_standard_image_keeps_verified_v1_snapshot_for_explicit_rollback():
    dockerfile = _read("Dockerfile")

    assert "all-MiniLM-L6-v2.json" in dockerfile
    assert "/opt/models/legacy-minilm-l6-v2" in dockerfile
    assert "/opt/models/multilingual-minilm-l12-v2" in dockerfile


def test_standard_image_contains_public_v2_materialization_assets():
    dockerfile = _read("Dockerfile")

    assert "materialize_kb_v2.py" in dockerfile
    assert "kb_v2/build" in dockerfile


def test_legacy_dockerfile_is_explicitly_non_default():
    legacy = _read("Dockerfile.legacy")
    legacy_ignore = _read("Dockerfile.legacy.dockerignore")

    assert "ragnxus-rag-api:0.5.17-backup" in legacy
    assert "LEGACY" in legacy
    assert "!.wheels/**" in legacy_ignore
    assert "!.env" not in legacy_ignore


def test_smoke_compose_uses_tmpfs_and_never_mounts_real_database():
    compose = _read("docker-compose.smoke.yml")

    assert "tmpfs:" in compose
    assert "/data/chroma_db" in compose
    assert "chroma_db:/data" not in compose
    assert "chroma_db_v2" not in compose
    assert "--workers 1" in compose
    assert "env_file" not in compose
    assert "smoke-placeholder-not-a-secret" in compose


def test_docker_context_excludes_local_and_sensitive_assets():
    dockerignore = _read(".dockerignore")

    for excluded in (".env", ".wheels/", ".agents/", "chroma_db*/", "models/*"):
        assert excluded in dockerignore
    assert "!models/manifests/" in dockerignore
    assert "!models/manifests/*.json" in dockerignore


def test_compose_defaults_to_candidate_and_exposes_explicit_embedding_switches():
    compose = _read("docker-compose.yml")

    assert "${RAG_CHROMA_HOST_DIR:-./chroma_db_v2_candidate}:/data/chroma_db" in compose
    assert "RAG_API_KEY=${RAG_API_KEY}" in compose
    assert "RAG_RATE_LIMIT=${RAG_RATE_LIMIT:-30}" in compose
    assert "RAG_EMBEDDING_MODEL_SOURCE=${RAG_EMBEDDING_MODEL_SOURCE:-/opt/models/multilingual-minilm-l12-v2}" in compose
    assert "RAG_EMBEDDING_MANIFEST=${RAG_EMBEDDING_MANIFEST:-/opt/models/manifests/paraphrase-multilingual-MiniLM-L12-v2.json}" in compose
    assert "kb-materialize:" in compose
    assert 'profiles: ["tools"]' in compose
    assert "python materialize_kb_v2.py" in compose


def test_runtime_embedding_defaults_are_pinned_by_tracked_manifest():
    config = resolve_embedding_runtime_config({}, ROOT)

    assert config.spec.model_id == (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert config.spec.revision == "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"  # pragma: allowlist secret -- public model revision
    assert config.spec.pooling == "masked_mean"


def test_api_image_copies_local_runtime_dependencies():
    for dockerfile_name in ("Dockerfile", "Dockerfile.legacy"):
        dockerfile = _read(dockerfile_name)
        assert "security_config.py" in dockerfile
        assert "document_ingest.py" in dockerfile
        assert "embedding_runtime.py" in dockerfile
        assert "agent_contract.py" in dockerfile
        assert "request_limits.py" in dockerfile


def test_snapshot_download_is_atomic_and_hash_checked(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "model.bin"
    source.write_bytes(b"immutable-model-bytes")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()

    _download(source.as_uri(), destination, expected)

    assert destination.read_bytes() == b"immutable-model-bytes"
    assert not destination.with_suffix(".bin.part").exists()


def test_snapshot_download_rejects_wrong_hash(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "model.bin"
    source.write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="SHA256 mismatch"):
        _download(source.as_uri(), destination, "0" * 64)

    assert not destination.exists()
    assert not destination.with_suffix(".bin.part").exists()


def test_snapshot_downloader_consumes_tracked_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        """{
          "model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
          "revision": "frozen-revision",
          "pooling": "masked_mean",
          "files": [
            {"path": "config.json", "size": 6, "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
          ]
        }""",
        encoding="utf-8",
    )

    spec = load_download_manifest(manifest)

    assert spec.model_id.endswith("paraphrase-multilingual-MiniLM-L12-v2")
    assert spec.revision == "frozen-revision"
    assert spec.files == {
        "config.json": {
            "size": 6,
            "sha256": "a" * 64,
        }
    }


def test_snapshot_downloader_rejects_unsafe_manifest_path(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        """{
          "model_id": "sentence-transformers/example",
          "revision": "frozen-revision",
          "pooling": "masked_mean",
          "files": [
            {"path": "../escape.bin", "size": 1, "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
          ]
        }""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsafe"):
        load_download_manifest(manifest)
