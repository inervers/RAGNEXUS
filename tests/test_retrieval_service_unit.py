import pytest

from retrieval_service import (
    GENERATION_SYSTEM_PROMPT,
    RetrievalConfig,
    RetrievalService,
    build_generation_context,
    build_sources,
    format_trace_summary,
    without_retrieval_tool,
)


class FakeSearch:
    def __init__(self):
        self.calls = []

    def search(self, query, top_k, dense_weight, sparse_weight):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "dense_weight": dense_weight,
                "sparse_weight": sparse_weight,
            }
        )
        return {
            "query": query,
            "dense_top": [
                {"id": "dense-a", "text": "DA"},
                {"id": "dense-b", "text": "DB"},
                {"id": "dense-c", "text": "DC"},
            ],
            "hybrid_top": [
                {"id": "hybrid-a", "text": "HA"},
                {"id": "hybrid-b", "text": "HB"},
                {"id": "hybrid-c", "text": "HC"},
            ],
            "stats": {"dense_count": 3, "sparse_count": 3, "overlap": 1},
        }


def _make_service(search=None, rerank=None):
    fake = search or FakeSearch()
    return (
        RetrievalService(
            search_provider=lambda: fake,
            rerank_provider=rerank,
            corpus_version_provider=lambda: 166,
        ),
        fake,
    )


def test_config_defaults_match_production_hybrid_policy():
    config = RetrievalConfig()

    assert config.strategy == "hybrid"
    assert config.top_k == 6
    assert config.dense_weight == 1.0
    assert config.sparse_weight == 2.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"strategy": "unknown"},
        {"top_k": 0},
        {"top_k": 51},
        {"dense_weight": 0},
        {"sparse_weight": -1},
    ],
)
def test_config_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        RetrievalConfig(**kwargs)


@pytest.mark.parametrize(
    ("strategy", "expected_ids"),
    [
        ("dense", ["dense-a", "dense-b"]),
        ("hybrid", ["hybrid-a", "hybrid-b"]),
    ],
)
def test_service_selects_strategy_and_emits_trace(strategy, expected_ids):
    service, search = _make_service()

    result = service.retrieve(
        "same query",
        RetrievalConfig(strategy=strategy, top_k=2),
        trace_id="trace-123",
    )

    assert [item["id"] for item in result["selected"]] == expected_ids
    assert result["trace"] == {
        "trace_id": "trace-123",
        "strategy": strategy,
        "top_k": 2,
        "dense_weight": 1.0,
        "sparse_weight": 2.0,
        "corpus_version": 166,
        "reranker_mode": None,
    }
    assert search.calls == [
        {
            "query": "same query",
            "top_k": 2,
            "dense_weight": 1.0,
            "sparse_weight": 2.0,
        }
    ]


def test_service_reranks_hybrid_candidates_and_records_actual_mode():
    def rerank(query, candidates, top_k):
        assert query == "q"
        assert [item["id"] for item in candidates] == [
            "hybrid-a",
            "hybrid-b",
            "hybrid-c",
        ]
        return list(reversed(candidates))[:top_k], {
            "mode": "cross_encoder",
            "reason": None,
        }

    service, _ = _make_service(rerank=rerank)

    result = service.retrieve(
        "q", RetrievalConfig(strategy="reranked", top_k=2), trace_id="t"
    )

    assert [item["id"] for item in result["selected"]] == [
        "hybrid-c",
        "hybrid-b",
    ]
    assert result["reranked"] == result["selected"]
    assert result["reranker_status"]["mode"] == "cross_encoder"
    assert result["trace"]["reranker_mode"] == "cross_encoder"


def test_service_rejects_blank_query():
    service, _ = _make_service()

    with pytest.raises(ValueError, match="query"):
        service.retrieve("  ", RetrievalConfig(), trace_id="t")


def test_generation_context_consumes_selected_chunks_only():
    retrieval = {
        "dense_top": [{"id": "dense-only", "text": "DENSE SHOULD NOT APPEAR"}],
        "hybrid_top": [{"id": "hybrid-only", "text": "HYBRID SHOULD NOT APPEAR"}],
        "selected": [
            {"id": "selected-a", "text": "selected text A"},
            {"id": "selected-b", "text": "selected text B"},
        ],
    }

    context = build_generation_context("original question", retrieval)

    assert "[selected-a] selected text A" in context
    assert "[selected-b] selected text B" in context
    assert "DENSE SHOULD NOT APPEAR" not in context
    assert "HYBRID SHOULD NOT APPEAR" not in context
    assert context.count("original question") == 1


def test_sources_preserve_selected_ids_and_order():
    retrieval = {
        "selected": [
            {"id": "chunk-b", "text": "B" * 400},
            {"id": "chunk-a", "text": "A"},
        ]
    }

    sources = build_sources("q", retrieval)

    assert [source["id"] for source in sources] == ["chunk-b", "chunk-a"]
    assert sources[0]["query"] == "q"
    assert len(sources[0]["content"]) == 300


def test_generation_tools_exclude_retrieval_but_keep_other_tools():
    tools = [
        {"type": "function", "function": {"name": "search_knowledge"}},
        {"type": "function", "function": {"name": "summarize"}},
        {"type": "function", "function": {"name": "translate"}},
    ]

    filtered = without_retrieval_tool(tools)

    assert [tool["function"]["name"] for tool in filtered] == [
        "summarize",
        "translate",
    ]
    assert len(tools) == 3


def test_generation_prompt_declares_context_is_already_retrieved():
    assert "已提供" in GENERATION_SYSTEM_PROMPT
    assert "search_knowledge" not in GENERATION_SYSTEM_PROMPT


def test_trace_summary_uses_same_service_trace_fields():
    summary = format_trace_summary(
        {
            "trace": {
                "trace_id": "trace-123",
                "strategy": "hybrid",
                "top_k": 5,
                "corpus_version": 166,
            }
        }
    )

    assert summary == (
        "trace_id=trace-123 strategy=hybrid top_k=5 corpus_version=166"
    )
