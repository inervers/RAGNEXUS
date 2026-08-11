"""Thread-safe SSE transport for the synchronous Agent writing workflow."""

import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator, Callable
from datetime import datetime


_STREAM_END = object()


def encode_sse(event: dict) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"data: {payload}\n\n"


def _failure_event(trace_id: str, sequence: int, error: Exception) -> dict:
    return {
        "type": "workflow_failed",
        "trace_id": trace_id,
        "sequence": sequence,
        "timestamp": datetime.now().isoformat(),
        "agent": "workflow",
        "attempt": None,
        "status": "fail",
        "duration_s": None,
        "tokens": None,
        "detail": {"error_type": type(error).__name__},
        "result": None,
    }


async def stream_workflow_events(
    workflow_factory: Callable,
    topic: str,
    max_retries: int,
    trace_id: str,
) -> AsyncIterator[str]:
    """Run a blocking workflow in a daemon thread and yield sanitized SSE frames."""
    events: queue.Queue = queue.Queue()
    stopped = threading.Event()

    def publish(event: dict) -> None:
        if not stopped.is_set():
            events.put(event)

    def run_workflow() -> None:
        workflow = None
        try:
            workflow = workflow_factory(
                event_callback=publish,
                trace_id=trace_id,
            )
            result = workflow.run(topic, max_retries=max_retries)
            workflow.trace.emit(
                "workflow_completed",
                "workflow",
                "ok",
                result=result,
            )
        except Exception as error:
            if workflow is not None and getattr(workflow, "trace", None) is not None:
                workflow.trace.emit(
                    "workflow_failed",
                    "workflow",
                    "fail",
                    detail={"error_type": type(error).__name__},
                )
            else:
                publish(_failure_event(trace_id, 1, error))
        finally:
            events.put(_STREAM_END)

    threading.Thread(target=run_workflow, daemon=True).start()
    try:
        while True:
            event = await asyncio.to_thread(events.get)
            if event is _STREAM_END:
                break
            yield encode_sse(event)
    finally:
        stopped.set()
