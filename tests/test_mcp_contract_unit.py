from pathlib import Path

import mcp_client_test
import mcp_server
import pytest


def test_call_api_propagates_response_trace_header(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"X-Trace-Id": "trace-header"}

        @staticmethod
        def json():
            return {"status": "ok"}

    monkeypatch.setattr(mcp_server.httpx, "get", lambda *args, **kwargs: FakeResponse())

    status, payload = mcp_server._call_api("/health")

    assert status == 200
    assert payload["trace_id"] == "trace-header"


def test_retrieve_knowledge_returns_structured_success(monkeypatch):
    def fake_call(path, payload=None):
        assert path == "/query/hybrid"
        assert payload == {
            "question": "混合检索",
            "top_k": 2,
            "strategy": "hybrid",
        }
        return (
            200,
            {
                "trace_id": "trace-mcp",
                "result": {
                    "selected": [
                        {"id": "chunk-a", "text": "A", "rrf_score": 0.0328},
                        {"id": "chunk-b", "text": "B", "rrf_score": 0.0164},
                    ],
                    "stats": {
                        "dense_count": 2,
                        "sparse_count": 2,
                        "overlap": 1,
                    },
                    "trace": {
                        "trace_id": "trace-mcp",
                        "strategy": "hybrid",
                        "top_k": 2,
                    },
                },
            },
        )

    monkeypatch.setattr(mcp_server, "_call_api", fake_call)

    payload = mcp_server.retrieve_knowledge("混合检索", top_k=2)

    assert payload == {
        "ok": True,
        "summary": "查询「混合检索」检索到 2 条相关内容",
        "query": "混合检索",
        "strategy": "hybrid",
        "trace_id": "trace-mcp",
        "chunks": [
            {"id": "chunk-a", "text": "A", "rrf_score": 0.0328},
            {"id": "chunk-b", "text": "B", "rrf_score": 0.0164},
        ],
        "stats": {"dense_count": 2, "sparse_count": 2, "overlap": 1},
    }


def test_retrieve_knowledge_returns_structured_empty_result(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "_call_api",
        lambda path, payload=None: (
            200,
            {
                "trace_id": "trace-empty",
                "result": {
                    "selected": [],
                    "stats": {"dense_count": 0, "sparse_count": 0, "overlap": 0},
                    "trace": {"trace_id": "trace-empty", "strategy": "hybrid"},
                },
            },
        ),
    )

    payload = mcp_server.retrieve_knowledge("不存在的问题")

    assert payload["ok"] is True
    assert payload["chunks"] == []
    assert payload["strategy"] == "hybrid"
    assert payload["trace_id"] == "trace-empty"
    assert "未检索到" in payload["summary"]


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [(401, "missing_api_key"), (403, "invalid_api_key"), (429, "rate_limited"), (0, "connection_error"), (500, "upstream_error")],
)
def test_retrieve_knowledge_returns_machine_readable_error(
    monkeypatch, status, expected_code
):
    monkeypatch.setattr(
        mcp_server,
        "_call_api",
        lambda path, payload=None: (
            status,
            {"error": "rate limited", "trace_id": "trace-rate"},
        ),
    )

    payload = mcp_server.retrieve_knowledge("q")

    assert payload["ok"] is False
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["trace_id"] == "trace-rate"
    assert payload["error"]["message"]


def test_kb_status_returns_structured_health(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "_call_api",
        lambda path, payload=None: (
            200,
            {
                "status": "ok",
                "version": "0.7.1",
                "chunks": 184,
                "tools": ["summarize", "translate"],
                "rate_limit": "30/min",
                "trace_id": "trace-health",
            },
        ),
    )

    payload = mcp_server.kb_status()

    assert payload == {
        "ok": True,
        "status": "ok",
        "version": "0.7.1",
        "chunks": 184,
        "tools": ["summarize", "translate"],
        "rate_limit": "30/min",
        "trace_id": "trace-health",
    }


def test_client_server_command_is_clone_independent():
    command, args = mcp_client_test.server_command()

    assert Path(command).resolve() == Path(mcp_client_test.sys.executable).resolve()
    assert args == [str(Path(mcp_client_test.__file__).resolve().with_name("mcp_server.py"))]
