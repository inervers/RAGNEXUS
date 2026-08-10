import pytest

import rag_advanced


def test_build_corpus_records_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="数量"):
        rag_advanced.build_corpus_records(["chunk-a"], ["A", "B"])


@pytest.mark.parametrize(
    ("ids", "documents", "message"),
    [
        (["chunk-a", "chunk-a"], ["A", "B"], "重复"),
        ([""], ["A"], "id"),
        (["chunk-a"], [""], "text"),
        ([None], ["A"], "id"),
        (["chunk-a"], [None], "text"),
    ],
)
def test_build_corpus_records_rejects_invalid_items(ids, documents, message):
    with pytest.raises(ValueError, match=message):
        rag_advanced.build_corpus_records(ids, documents)


def test_build_corpus_records_allows_empty_corpus():
    assert rag_advanced.build_corpus_records([], []) == []


class FakeBM25:
    def __init__(self, tokenized):
        self.size = len(tokenized)

    def get_scores(self, tokens):
        return [1.0] + [0.0] * (self.size - 1)


class FakeCollection:
    def query(self, **kwargs):
        return {
            "ids": [["chunk-real-a"]],
            "documents": [["混合检索"]],
            "distances": [[0.2]],
        }


def _install_fake_bm25(monkeypatch):
    monkeypatch.setattr(rag_advanced, "BM25Okapi", FakeBM25)
    monkeypatch.setattr(rag_advanced, "_tokenize", lambda _: ["token"])


def test_sparse_search_preserves_chroma_id(monkeypatch):
    _install_fake_bm25(monkeypatch)
    records = [{"id": "chunk-real-a", "text": "混合检索"}]
    search = rag_advanced.HybridSearch(FakeCollection(), lambda _: [], records)

    assert search.sparse_search("检索") == [
        {"id": "chunk-real-a", "text": "混合检索", "score": 1.0}
    ]


def test_search_fuses_same_chunk_once(monkeypatch):
    _install_fake_bm25(monkeypatch)
    records = [{"id": "chunk-real-a", "text": "混合检索"}]
    search = rag_advanced.HybridSearch(FakeCollection(), lambda _: [], records)

    result = search.search("检索", top_k=5)

    assert [item["id"] for item in result["hybrid_top"]] == ["chunk-real-a"]
    assert result["stats"]["overlap"] == 1
    assert result["hybrid_top"][0]["rrf_score"] == round(2 / 61, 4)


def test_set_corpus_rebuilds_id_text_mapping(monkeypatch):
    _install_fake_bm25(monkeypatch)
    search = rag_advanced.HybridSearch(
        FakeCollection(), lambda _: [], [{"id": "old", "text": "旧文本"}]
    )
    refreshed = [
        {"id": "chunk-b", "text": "新文本B"},
        {"id": "chunk-a", "text": "新文本A"},
    ]

    search.set_corpus(refreshed)
    refreshed[0]["id"] = "mutated"

    assert search.sparse_search("新文本") == [
        {"id": "chunk-b", "text": "新文本B", "score": 1.0}
    ]


def test_empty_corpus_disables_sparse_search(monkeypatch):
    _install_fake_bm25(monkeypatch)
    search = rag_advanced.HybridSearch(FakeCollection(), lambda _: [], [])

    assert search.sparse_search("anything") == []


class FakeCrossEncoder:
    def __init__(self):
        self.pairs = []

    def predict(self, pairs):
        self.pairs = list(pairs)
        return [0.2, 0.9]


def test_reranker_deduplicates_ids_before_model_call():
    reranker = rag_advanced.Reranker.__new__(rag_advanced.Reranker)
    reranker.model = FakeCrossEncoder()
    candidates = [
        {"id": "chunk-a", "text": "A1", "rrf_score": 0.3},
        {"id": "chunk-a", "text": "A2", "rrf_score": 0.2},
        {"id": "chunk-b", "text": "B", "rrf_score": 0.1},
    ]

    result = reranker.rerank("query", candidates, top_k=5)

    assert reranker.model.pairs == [("query", "A1"), ("query", "B")]
    assert [item["id"] for item in result] == ["chunk-b", "chunk-a"]


def test_reranker_fallback_deduplicates_ids():
    reranker = rag_advanced.Reranker.__new__(rag_advanced.Reranker)
    reranker.model = None
    candidates = [
        {"id": "chunk-a", "text": "A1", "score": 0.3},
        {"id": "chunk-a", "text": "A2", "score": 0.2},
        {"id": "chunk-b", "text": "B", "score": 0.1},
    ]

    result = reranker.rerank("query", candidates, top_k=5)

    assert [item["id"] for item in result] == ["chunk-a", "chunk-b"]


@pytest.mark.parametrize("bad_id", [None, "", "  "])
def test_reranker_rejects_invalid_candidate_id(bad_id):
    reranker = rag_advanced.Reranker.__new__(rag_advanced.Reranker)
    reranker.model = None

    with pytest.raises(ValueError, match="id"):
        reranker.rerank("query", [{"id": bad_id, "text": "A"}])
