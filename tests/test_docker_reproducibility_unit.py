from pathlib import Path
import hashlib

import pytest

from scripts.download_embedding_snapshot import _download


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_default_dockerfile_is_independent_of_personal_build_assets():
    dockerfile = _read("Dockerfile")

    assert "FROM python:3.11-slim" in dockerfile
    assert "ragnxus-rag-api" not in dockerfile
    assert ".wheels" not in dockerfile
    assert "requirements-api.txt" in dockerfile
    assert "RAG_EMBEDDING_MODEL_REVISION" in dockerfile
    assert "1110a243fdf4706b3f48f1d95db1a4f5529b4d41" in dockerfile  # pragma: allowlist secret -- public model revision


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

    for excluded in (".env", ".wheels/", ".agents/", "chroma_db*/", "models/"):
        assert excluded in dockerignore


def test_runtime_embedding_revision_is_configurable_and_pinned_by_default():
    api = _read("rag_api.py")

    assert "EMBEDDING_MODEL_ID = os.environ.get(" in api
    assert '"RAG_EMBEDDING_MODEL_ID"' in api
    assert "EMBEDDING_MODEL_REVISION = os.environ.get(" in api
    assert '"RAG_EMBEDDING_MODEL_REVISION"' in api
    assert "revision=EMBEDDING_MODEL_REVISION" in api
    assert "local_files_only=True" in api


def test_api_image_copies_local_runtime_dependencies():
    for dockerfile_name in ("Dockerfile", "Dockerfile.legacy"):
        dockerfile = _read(dockerfile_name)
        assert "security_config.py" in dockerfile
        assert "document_ingest.py" in dockerfile
        assert "embedding_runtime.py" in dockerfile


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
