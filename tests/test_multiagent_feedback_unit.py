import json

import rag_multiagent
from rag_multiagent import MultiAgentWorkflow, TraceLogger


def run_workflow(monkeypatch, tmp_path, review_ratings: list[int]):
    real_memory = rag_multiagent.AgentMemory
    monkeypatch.setattr(
        rag_multiagent,
        "AgentMemory",
        lambda name: real_memory(name, base_dir=str(tmp_path)),
    )

    workflow = object.__new__(MultiAgentWorkflow)
    workflow.trace = TraceLogger()
    workflow.knowledge_fn = None
    calls: list[tuple[str, str]] = []
    responses = [json.dumps({"key_points": ["事实"], "confidence": 0.9})]
    for attempt, rating in enumerate(review_ratings, start=1):
        responses.extend(
            [
                json.dumps({"title": f"第{attempt}稿", "content": "正文", "word_count": 2}),
                json.dumps(
                    {
                        "issues": ["缺少可核验引用"],
                        "rating": rating,
                        "verdict": "通过" if rating >= 4 else "需要修改",
                    }
                ),
            ]
        )

    def fake_llm(system: str, user: str, temperature: float = 0.3) -> str:
        calls.append((system, user))
        return responses[len(calls) - 1]

    workflow._call_llm = fake_llm
    result = workflow.run("RAG", max_retries=len(review_ratings) - 1)
    return result, calls, workflow.trace.events


def test_reviewer_issues_reach_next_writer_prompt_and_trace(monkeypatch, tmp_path) -> None:
    result, calls, events = run_workflow(monkeypatch, tmp_path, [2, 4])

    second_writer_user_prompt = calls[3][1]
    assert "上一轮审核反馈" in second_writer_user_prompt
    assert "缺少可核验引用" in second_writer_user_prompt
    assert any(
        event["agent"] == "reviewer"
        and event["action"] == "feedback_to_writer"
        and event["target"] == "writer"
        and event["issue_count"] == 1
        for event in events
    )
    assert result["passed"] is True
    assert result["attempts"] == 2


def test_rating_improvement_below_threshold_does_not_fake_a_pass(monkeypatch, tmp_path) -> None:
    result, _, _ = run_workflow(monkeypatch, tmp_path, [2, 3])

    assert result["passed"] is False
    assert result["rating"] == 3
    assert result["verdict"] == "需要修改"
    assert result["attempts"] == 2
