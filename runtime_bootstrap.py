"""Startup guards that keep production databases free of smoke fixtures."""

from __future__ import annotations

from typing import Mapping


class BootstrapConfigurationError(ValueError):
    pass


def should_seed_initial_fixtures(
    environ: Mapping[str, str], collection_count: int
) -> bool:
    raw = environ.get("RAG_SEED_INITIAL_FIXTURES", "0").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        enabled = False
    elif raw in {"1", "true", "yes", "on"}:
        enabled = True
    else:
        raise BootstrapConfigurationError(
            "RAG_SEED_INITIAL_FIXTURES must be a boolean value"
        )
    return enabled and collection_count == 0
