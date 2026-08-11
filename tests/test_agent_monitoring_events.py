import json
from types import SimpleNamespace

import pytest

import rag_multiagent
from rag_multiagent import MultiAgentWorkflow, TraceLogger


class FakeCompletions:
    def __init__(self, responses, token_counts):
        self.responses = list(responses)
        self.token_counts = list(token_counts)

    def create(self, **_kwargs):
        content = self.responses.pop(0)
        tokens = self.token_counts.pop(0)
        usage = None if tokens is None else SimpleNamespace(total_tokens=tokens)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=usage,
        )


class FailingCompletions:
    def create(self, **_kwargs):
        raise RuntimeError("secret-value-that-must-not-leak")


def build_workflow(monkeypatch, tmp_path, responses, token_counts, events):
    real_memory = rag_multiagent.AgentMemory
    monkeypatch.setattr(
        rag_multiagent,
        "AgentMemory",
        lambda name: real_memory(name, base_dir=str(tmp_path)),
    )
    workflow = object.__new__(MultiAgentWorkflow)
    workflow.model = "fake-model"
    workflow.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions(responses, token_counts))
    )
    workflow.trace = TraceLogger(trace_id="trace-test", event_callback=events.append)
    workflow.knowledge_fn = lambda _query, top_k: [
        {"id": "doc-1", "text": "RAG 通过检索提供上下文", "score": 0.9}
    ][:top_k]
    return workflow


def passing_responses():
    return [
        json.dumps({"key_points": ["事实"], "confidence": 0.9}),
        json.dumps({"title": "文章", "content": "正文", "word_count": 2}),
        json.dumps({"issues": [], "rating": 4, "verdict": "通过"}),
    ]


def test_workflow_emits_role_events_with_real_metrics(monkeypatch, tmp_path):
    events = []
    workflow = build_workflow(
        monkeypatch, tmp_path, passing_responses(), [11, 22, 7], events
    )

    result = workflow.run("RAG", max_retries=0)

    completed = [event for event in events if event["type"] == "agent_completed"]
    assert [event["agent"] for event in completed] == [
        "researcher",
        "writer",
        "reviewer",
    ]
    assert [event["tokens"] for event in completed] == [11, 22, 7]
    assert all(event["duration_s"] >= 0 for event in completed)
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert completed[0]["detail"]["kb_docs"] == 1
    assert result["monitor"]["agent_metrics"]["writer"]["calls"] == 1
    assert result["monitor"]["agent_metrics"]["writer"]["total_tokens"] == 22


def test_review_and_retry_events_match_the_real_review(monkeypatch, tmp_path):
    events = []
    responses = [
        json.dumps({"key_points": ["事实"], "confidence": 0.9}),
        json.dumps({"title": "第一稿", "content": "正文", "word_count": 2}),
        json.dumps({"issues": ["缺少引用"], "rating": 2, "verdict": "需要修改"}),
        json.dumps({"title": "第二稿", "content": "改进正文", "word_count": 4}),
        json.dumps({"issues": [], "rating": 4, "verdict": "通过"}),
    ]
    workflow = build_workflow(
        monkeypatch, tmp_path, responses, [3, 5, 2, 6, 2], events
    )

    result = workflow.run("RAG", max_retries=1)

    reviews = [event for event in events if event["type"] == "review_completed"]
    retries = [event for event in events if event["type"] == "retry_scheduled"]
    assert [(event["attempt"], event["detail"]) for event in reviews] == [
        (1, {"rating": 2, "verdict": "需要修改", "issue_count": 1}),
        (2, {"rating": 4, "verdict": "通过", "issue_count": 0}),
    ]
    assert len(retries) == 1
    assert retries[0]["attempt"] == 1
    assert retries[0]["detail"]["next_attempt"] == 2
    assert retries[0]["detail"]["issue_count"] == 1
    assert result["attempts"] == 2
    assert result["passed"] is True


def test_missing_provider_usage_remains_unknown(monkeypatch, tmp_path):
    events = []
    workflow = build_workflow(
        monkeypatch, tmp_path, passing_responses(), [None, None, None], events
    )

    result = workflow.run("RAG", max_retries=0)

    completed = [event for event in events if event["type"] == "agent_completed"]
    assert all(event["tokens"] is None for event in completed)
    assert result["monitor"]["agent_metrics"]["researcher"]["total_tokens"] is None


def test_failed_role_event_does_not_leak_the_exception_message(monkeypatch, tmp_path):
    events = []
    real_memory = rag_multiagent.AgentMemory
    monkeypatch.setattr(
        rag_multiagent,
        "AgentMemory",
        lambda name: real_memory(name, base_dir=str(tmp_path)),
    )
    workflow = object.__new__(MultiAgentWorkflow)
    workflow.model = "fake-model"
    workflow.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FailingCompletions())
    )
    workflow.trace = TraceLogger(trace_id="trace-fail", event_callback=events.append)
    workflow.knowledge_fn = None

    with pytest.raises(RuntimeError, match="secret-value"):
        workflow.run("RAG", max_retries=0)

    assert events[-1]["type"] == "agent_failed"
    assert events[-1]["agent"] == "researcher"
    assert events[-1]["detail"] == {"error_type": "RuntimeError"}
    assert "secret-value" not in json.dumps(events[-1])
