import pytest

import eval_rag


def test_id_based_metrics_are_hand_calculable():
    docs = [
        {"id": "X", "text": "mentions A but is not relevant"},
        {"id": "A", "text": "first relevant"},
        {"id": "C", "text": "second relevant"},
    ]
    relevant_ids = ["A", "C"]

    assert eval_rag.recall_at_k(docs, relevant_ids, 1) == 0.0
    assert eval_rag.recall_at_k(docs, relevant_ids, 2) == 0.5
    assert eval_rag.recall_at_k(docs, relevant_ids, 5) == 1.0
    assert eval_rag.hit_at_k(docs, relevant_ids, 5) == 1.0
    assert eval_rag.mrr_at_k(docs, relevant_ids, 10) == 0.5


def test_mrr_respects_cutoff():
    docs = [{"id": f"noise-{i}"} for i in range(10)] + [{"id": "A"}]

    assert eval_rag.mrr_at_k(docs, ["A"], 10) == 0.0
    assert eval_rag.mrr_at_k(docs, ["A"], 11) == pytest.approx(1 / 11)


def test_score_retrieval_result_marks_successful_empty_as_zero_quality():
    result = eval_rag.score_retrieval_result([], ["A"])

    assert result == {
        "status": "empty",
        "n": 0,
        "metrics": {
            "recall_at_5": 0.0,
            "recall_at_10": 0.0,
            "mrr_at_10": 0.0,
            "hit_rate_at_5": 0.0,
        },
    }


@pytest.mark.parametrize("relevant_ids", [None, []])
def test_score_retrieval_result_without_ground_truth_is_unscored(relevant_ids):
    result = eval_rag.score_retrieval_result([{"id": "A"}], relevant_ids)

    assert result == {
        "status": "unscored",
        "reason": "missing_relevant_chunk_ids",
    }
    assert "metrics" not in result


@pytest.mark.parametrize("bad_doc", [{}, {"id": ""}, {"id": None}, {"id": 7}])
def test_id_metrics_reject_invalid_result_ids(bad_doc):
    with pytest.raises(ValueError, match="非空字符串"):
        eval_rag.recall_at_k([bad_doc], ["A"], 5)


def test_evaluate_strategy_does_not_score_api_errors():
    def failing_post(path, body):
        raise TimeoutError("service timed out")

    result = eval_rag.evaluate_strategy(
        {"question": "q", "relevant_chunk_ids": ["A"]},
        ("dense", {"use_reranker": False}, "dense_top"),
        post=failing_post,
    )

    assert result == {"status": "error", "reason": "service timed out"}
    assert "metrics" not in result


def test_evaluate_strategy_skips_request_without_ground_truth():
    called = False

    def unexpected_post(path, body):
        nonlocal called
        called = True
        return {}

    result = eval_rag.evaluate_strategy(
        {"question": "legacy question", "expected_keywords": ["legacy"]},
        ("dense", {"use_reranker": False}, "dense_top"),
        post=unexpected_post,
    )

    assert result["status"] == "unscored"
    assert called is False


def test_evaluate_strategy_scores_successful_empty_response():
    def empty_post(path, body):
        return {"result": {"dense_top": []}}

    result = eval_rag.evaluate_strategy(
        {"question": "q", "relevant_chunk_ids": ["A"]},
        ("dense", {"use_reranker": False}, "dense_top"),
        post=empty_post,
    )

    assert result["status"] == "empty"
    assert set(result["metrics"].values()) == {0.0}


def test_aggregate_excludes_errors_and_unscored_but_includes_empty():
    metric_names = (
        "recall_at_5",
        "recall_at_10",
        "mrr_at_10",
        "hit_rate_at_5",
    )

    def metrics(value):
        return {name: value for name in metric_names}

    questions = [
        {"retrieval": {"dense": {"status": "ok", "n": 2, "metrics": metrics(1.0)}}},
        {"retrieval": {"dense": {"status": "empty", "n": 0, "metrics": metrics(0.0)}}},
        {"retrieval": {"dense": {"status": "error", "reason": "timeout"}}},
        {"retrieval": {"dense": {"status": "unscored", "reason": "missing"}}},
    ]

    aggregate = eval_rag.aggregate_retrieval_results(questions)

    assert aggregate["dense"]["counts"] == {
        "total": 4,
        "scored": 2,
        "ok": 1,
        "empty": 1,
        "error": 1,
        "unscored": 1,
        "fallback": 0,
    }
    assert aggregate["dense"]["metrics"] == metrics(0.5)


def test_reranker_fallback_is_not_scored_as_cross_encoder_quality():
    def fallback_post(path, body):
        return {
            "result": {
                "reranked": [{"id": "A"}],
                "reranker_status": {
                    "mode": "fallback",
                    "reason": "model_load_failed:OSError",
                },
            }
        }

    result = eval_rag.evaluate_strategy(
        {"question": "q", "relevant_chunk_ids": ["A"]},
        ("reranked", {"use_reranker": True}, "reranked"),
        post=fallback_post,
    )

    assert result == {
        "status": "fallback",
        "reason": "model_load_failed:OSError",
        "n": 1,
    }
    assert "metrics" not in result


def test_reranker_response_without_status_is_an_execution_error():
    def legacy_post(path, body):
        return {"result": {"reranked": [{"id": "A"}]}}

    result = eval_rag.evaluate_strategy(
        {"question": "q", "relevant_chunk_ids": ["A"]},
        ("reranked", {"use_reranker": True}, "reranked"),
        post=legacy_post,
    )

    assert result["status"] == "error"
    assert "reranker_status" in result["reason"]
    assert "metrics" not in result


@pytest.mark.parametrize(
    ("inner_errors", "fatal_error", "expected"),
    [
        ([], None, "OK"),
        (["dense:timeout"], None, "WARN dense:timeout"),
        ([], "broken", "ERROR broken"),
    ],
)
def test_progress_status_is_safe_for_windows_gbk_console(
    inner_errors, fatal_error, expected
):
    status = eval_rag.format_progress_status(inner_errors, fatal_error)

    assert status == expected
    status.encode("gbk")


def test_progress_status_reports_unscored_instead_of_ok():
    status = eval_rag.format_progress_status(
        [], None, notices=["UNSCORED missing_relevant_chunk_ids"]
    )

    assert status == "UNSCORED missing_relevant_chunk_ids"


def test_result_output_message_uses_actual_path():
    assert eval_rag.result_output_message("custom/result.json") == (
        "评测结果已写入 custom/result.json"
    )
