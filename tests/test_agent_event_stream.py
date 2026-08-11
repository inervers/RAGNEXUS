import asyncio
import json
from datetime import datetime

from agent_event_stream import encode_sse, stream_workflow_events


class FakeTrace:
    def __init__(self, trace_id, callback):
        self.trace_id = trace_id
        self.callback = callback
        self.sequence = 0

    def emit(self, event_type, agent, status, *, result=None, detail=None, **fields):
        self.sequence += 1
        event = {
            "type": event_type,
            "trace_id": self.trace_id,
            "sequence": self.sequence,
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "attempt": fields.get("attempt"),
            "status": status,
            "duration_s": fields.get("duration_s"),
            "tokens": fields.get("tokens"),
            "detail": detail or {},
            "result": result,
        }
        self.callback(event)
        return event


class FakeWorkflow:
    def __init__(self, event_callback, trace_id, fail=False):
        self.trace = FakeTrace(trace_id, event_callback)
        self.fail = fail

    def run(self, _topic, max_retries):
        self.trace.emit(
            "agent_started", "researcher", "running", attempt=None
        )
        if self.fail:
            raise RuntimeError("secret-value-that-must-not-leak")
        self.trace.emit(
            "agent_completed",
            "researcher",
            "ok",
            duration_s=0.25,
            tokens=13,
        )
        return {
            "article": "正文",
            "attempts": max_retries + 1,
            "passed": True,
        }


def decode_frame(frame):
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    return json.loads(frame[6:-2])


async def collect(factory):
    return [
        decode_frame(frame)
        async for frame in stream_workflow_events(factory, "RAG", 0, "trace-123")
    ]


def test_stream_emits_each_event_and_completes():
    payloads = asyncio.run(
        collect(
            lambda event_callback, trace_id: FakeWorkflow(
                event_callback, trace_id
            )
        )
    )

    assert [payload["type"] for payload in payloads] == [
        "agent_started",
        "agent_completed",
        "workflow_completed",
    ]
    assert [payload["sequence"] for payload in payloads] == [1, 2, 3]
    assert payloads[-1]["result"]["article"] == "正文"


def test_stream_sanitizes_unhandled_failures():
    payloads = asyncio.run(
        collect(
            lambda event_callback, trace_id: FakeWorkflow(
                event_callback, trace_id, fail=True
            )
        )
    )

    assert payloads[-1]["type"] == "workflow_failed"
    assert payloads[-1]["detail"] == {"error_type": "RuntimeError"}
    assert "secret-value" not in json.dumps(payloads[-1])


def test_sse_encoding_preserves_unicode_without_breaking_frames():
    frame = encode_sse(
        {
            "type": "review_completed",
            "detail": {"verdict": "需要\n修改"},
        }
    )

    assert frame.count("\n\n") == 1
    assert decode_frame(frame)["detail"]["verdict"] == "需要\n修改"
