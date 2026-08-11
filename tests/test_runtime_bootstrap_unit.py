import pytest

from runtime_bootstrap import BootstrapConfigurationError, should_seed_initial_fixtures


def test_production_empty_collection_is_not_seeded_by_default() -> None:
    assert should_seed_initial_fixtures({}, collection_count=0) is False


def test_smoke_can_explicitly_seed_an_empty_collection() -> None:
    assert (
        should_seed_initial_fixtures(
            {"RAG_SEED_INITIAL_FIXTURES": "1"}, collection_count=0
        )
        is True
    )


def test_seed_flag_never_mutates_a_nonempty_collection() -> None:
    assert (
        should_seed_initial_fixtures(
            {"RAG_SEED_INITIAL_FIXTURES": "true"}, collection_count=184
        )
        is False
    )


def test_seed_flag_rejects_ambiguous_values() -> None:
    with pytest.raises(BootstrapConfigurationError, match="RAG_SEED_INITIAL_FIXTURES"):
        should_seed_initial_fixtures(
            {"RAG_SEED_INITIAL_FIXTURES": "sometimes"}, collection_count=0
        )
