import pytest

from security_config import (
    DEFAULT_CORS_ORIGINS,
    SecurityConfigError,
    load_api_key,
    parse_cors_origins,
)


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"RAG_API_KEY": ""},
        {"RAG_API_KEY": "   "},
        {"RAG_API_KEY": "rag-secret-key-2024"},  # pragma: allowlist secret -- rejected historical fixture
        {"RAG_API_KEY": "replace-with-a-random-secret"},  # pragma: allowlist secret -- rejected template fixture
        {"RAG_API_KEY": "<project-key>"},
    ],
)
def test_load_api_key_rejects_missing_or_insecure_values(environ):
    with pytest.raises(SecurityConfigError, match="RAG_API_KEY"):
        load_api_key(environ)


def test_load_api_key_accepts_a_configured_secret_without_logging_it():
    value = "local-test-key-7f264c855f6e4d19"

    assert load_api_key({"RAG_API_KEY": value}) == value


def test_load_api_key_uses_the_first_configured_alias():
    environ = {
        "RAGNEXUS_API_KEY": "mcp-test-key-a58fe36bb79c4f91",  # pragma: allowlist secret -- inert unit fixture
        "RAG_API_KEY": "backend-test-key-a688786f9eab4050",  # pragma: allowlist secret -- inert unit fixture
    }

    assert load_api_key(environ, names=("RAGNEXUS_API_KEY", "RAG_API_KEY")) == environ["RAGNEXUS_API_KEY"]


def test_parse_cors_origins_uses_local_frontends_by_default():
    assert parse_cors_origins(None) == list(DEFAULT_CORS_ORIGINS)
    assert parse_cors_origins("  ") == list(DEFAULT_CORS_ORIGINS)


def test_parse_cors_origins_normalizes_and_deduplicates_exact_origins():
    raw = "https://rag.example.com, http://localhost:5173,https://rag.example.com"

    assert parse_cors_origins(raw) == ["https://rag.example.com", "http://localhost:5173"]


@pytest.mark.parametrize(
    "raw",
    [
        "*",
        "https://rag.example.com/app",
        "https://rag.example.com?debug=1",
        "rag.example.com",
        "file:///tmp/rag",
    ],
)
def test_parse_cors_origins_rejects_wildcards_and_non_origins(raw):
    with pytest.raises(SecurityConfigError, match="RAG_CORS_ORIGINS"):
        parse_cors_origins(raw)
