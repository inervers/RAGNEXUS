"""Pure security configuration parsing for API and client entry points."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit


class SecurityConfigError(RuntimeError):
    """Raised when a security-sensitive runtime setting is unsafe or missing."""


DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
)

_KNOWN_INSECURE_KEYS = frozenset({"rag-secret-key-2024"})


def _is_placeholder(value: str) -> bool:
    lowered = value.casefold()
    return (
        lowered in _KNOWN_INSECURE_KEYS
        or "replace-with" in lowered
        or "your-key" in lowered
        or (value.startswith("<") and value.endswith(">"))
    )


def load_api_key(
    environ: Mapping[str, str],
    names: Sequence[str] = ("RAG_API_KEY",),
) -> str:
    """Return the first safe configured key or fail without echoing its value."""
    for name in names:
        value = environ.get(name, "").strip()
        if value:
            if _is_placeholder(value):
                raise SecurityConfigError(f"{name} must not use a repository example or placeholder value")
            return value
    joined = " or ".join(names)
    raise SecurityConfigError(f"Missing required {joined}")


def load_api_key_from_sources(
    environ: Mapping[str, str],
    env_path: str | Path,
    environment_names: Sequence[str] = ("RAG_API_KEY",),
    file_name: str = "RAG_API_KEY",
) -> str:
    """Load an explicit process value, otherwise one value from a project env file."""
    if any(environ.get(name, "").strip() for name in environment_names):
        return load_api_key(environ, names=environment_names)

    values: dict[str, str] = {}
    try:
        for raw_line in Path(env_path).read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return load_api_key(values, names=(file_name,))


def parse_cors_origins(raw: str | None) -> list[str]:
    """Parse comma-separated exact HTTP(S) origins, rejecting wildcard/path forms."""
    if raw is None or not raw.strip():
        return list(DEFAULT_CORS_ORIGINS)

    origins: list[str] = []
    for candidate in raw.split(","):
        origin = candidate.strip().rstrip("/")
        parsed = urlsplit(origin)
        is_exact_origin = (
            origin != "*"
            and parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
            and not parsed.username
            and not parsed.password
            and parsed.path == ""
            and not parsed.query
            and not parsed.fragment
        )
        if not is_exact_origin:
            raise SecurityConfigError(
                "RAG_CORS_ORIGINS must contain exact http(s) origins and must not contain '*'"
            )
        if origin not in origins:
            origins.append(origin)

    if not origins:
        raise SecurityConfigError("RAG_CORS_ORIGINS must contain at least one origin")
    return origins
