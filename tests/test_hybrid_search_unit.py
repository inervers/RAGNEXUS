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
