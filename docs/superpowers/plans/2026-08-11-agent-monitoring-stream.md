# Agent Writing Real-Time Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace misleading post-hoc Agent cards with a real SSE event stream whose role status, duration, Token usage, review outcome, and retries come from actual workflow execution.

**Architecture:** `MultiAgentWorkflow` emits sanitized structured events through an optional callback while preserving the synchronous result API. A focused transport module bridges the blocking workflow to FastAPI SSE through a thread-safe queue. The React frontend parses SSE in a pure helper module, reduces events into role state and metrics, and renders a live timeline plus the existing final article.

**Tech Stack:** Python 3.11, FastAPI, `asyncio`, `queue.Queue`, pytest, React 19, TypeScript 6, Node test runner, Vite.

## Global Constraints

- Keep `POST /agent/write` response-compatible.
- Add `POST /agent/write/stream` using `data: <JSON>\n\n` SSE frames.
- Do not emit API keys, full prompts, knowledge-base text, or raw exception messages.
- Token usage is `null` when the provider omits usage; never substitute a fake zero.
- Preserve retry validation and the existing `rating >= 4` pass rule.
- Do not add a database, task queue, WebSocket, pause/resume, or upstream LLM cancellation.
- Do not modify `.agents/`, `docs/EVAL.md`, or `kb_summary.txt`.

---

### Task 1: Emit truthful role-level workflow events

**Files:**
- Modify: `rag_multiagent.py:107-365`
- Modify: `tests/test_multiagent_feedback_unit.py`
- Create: `tests/test_agent_monitoring_events.py`

**Interfaces:**
- Consumes: existing `MultiAgentWorkflow.run(topic: str, max_retries: int) -> dict`.
- Produces: `TraceLogger(trace_id: str | None = None, event_callback: Callable[[dict], None] | None = None)` and `TraceLogger.emit(event_type: str, agent: str, status: str, *, attempt: int | None = None, duration_s: float | None = None, tokens: int | None = None, detail: dict | None = None, result: dict | None = None) -> dict`, with strictly increasing `sequence`.
- Produces: `_call_llm(system: str, user: str, temperature: float = 0.3, *, agent: str = "llm", attempt: int | None = None, event_detail: dict | None = None) -> str` while preserving defaults for direct tests.

- [ ] **Step 1: Write failing event tests**

Add tests that construct a workflow with a fake OpenAI-compatible client and assert on real behavior:

```python
def test_workflow_emits_role_events_with_real_metrics(monkeypatch, tmp_path):
    events = []
    workflow = build_fake_workflow(
        monkeypatch,
        tmp_path,
        events,
        responses=[research_response(), article_response(), passing_review_response()],
        usage_tokens=[11, 22, 7],
    )

    result = workflow.run("RAG", max_retries=0)

    completed = [e for e in events if e["type"] == "agent_completed"]
    assert [e["agent"] for e in completed] == ["researcher", "writer", "reviewer"]
    assert [e["tokens"] for e in completed] == [11, 22, 7]
    assert all(e["duration_s"] >= 0 for e in completed)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert result["monitor"]["agent_metrics"]["writer"]["calls"] == 1
```

Also add one retry test asserting `review_completed`, `retry_scheduled`, attempt numbers, rating, verdict, and issue count; one missing-usage test asserting `tokens is None`; and one client-error test asserting an `agent_failed` event without the injected secret string.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_agent_monitoring_events.py -q
```

Expected: FAIL because `TraceLogger` has no event callback or event `type`/`sequence`, and `_call_llm` cannot attribute usage to roles.

- [ ] **Step 3: Implement event emission minimally**

Change `TraceLogger` to own sequence generation and sanitized callback delivery:

```python
class TraceLogger:
    def __init__(self, trace_id=None, event_callback=None):
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.event_callback = event_callback
        self.events = []
        self.sequence = 0

    def emit(self, event_type, agent, status, *, attempt=None,
             duration_s=None, tokens=None, detail=None, result=None):
        self.sequence += 1
        event = {
            "type": event_type,
            "trace_id": self.trace_id,
            "sequence": self.sequence,
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "attempt": attempt,
            "status": status,
            "duration_s": round(duration_s, 2) if duration_s is not None else None,
            "tokens": tokens,
            "detail": detail or {},
            "result": result,
        }
        self.events.append(event)
        if self.event_callback:
            self.event_callback(event.copy())
        return event
```

Update `_call_llm` so it emits `agent_started`, then either `agent_completed` with actual usage/duration or `agent_failed` with only `{"error_type": type(error).__name__}` before re-raising. Pass `agent`, `attempt`, and safe detail from each workflow role. Emit `review_completed` after parsing and `retry_scheduled` only when another attempt will occur.

Rewrite `summary()` to aggregate only `agent_completed` and `agent_failed`; compute calls, successes, durations, and `total_tokens`, using `None` when no completed event has provider usage.

- [ ] **Step 4: Adapt existing feedback tests to the truthful interface**

Update fake `_call_llm` functions to accept keyword-only role metadata:

```python
def fake_llm(system, user, temperature=0.3, **_event_context):
    calls.append((system, user))
    return responses[len(calls) - 1]
```

Assert retry feedback from the `retry_scheduled` event detail instead of the old pre-emptive `feedback_to_writer` success log.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_agent_monitoring_events.py tests/test_multiagent_feedback_unit.py -q
```

Expected: all focused tests pass, and Researcher/Writer/Reviewer metrics no longer contain zero-duration pre-success events.

- [ ] **Step 6: Commit Task 1**

```powershell
git add rag_multiagent.py tests/test_agent_monitoring_events.py tests/test_multiagent_feedback_unit.py
git commit -m "fix: record truthful agent execution metrics"
```

---

### Task 2: Stream workflow events through a safe SSE transport

**Files:**
- Create: `agent_event_stream.py`
- Modify: `rag_api.py:725-744`
- Create: `tests/test_agent_event_stream.py`

**Interfaces:**
- Consumes: a workflow factory accepting `event_callback` and `trace_id`.
- Produces: `encode_sse(event: dict) -> str` and `stream_workflow_events(workflow_factory, topic, max_retries, trace_id) -> AsyncIterator[str]`.
- Produces: authenticated `POST /agent/write/stream` with media type `text/event-stream`.

- [ ] **Step 1: Write failing transport tests**

```python
@pytest.mark.asyncio
async def test_stream_emits_each_event_and_completes():
    frames = [frame async for frame in stream_workflow_events(
        fake_workflow_factory, "RAG", 0, "trace-123"
    )]
    payloads = [json.loads(frame.removeprefix("data: ").strip()) for frame in frames]
    assert [p["type"] for p in payloads] == [
        "agent_started", "agent_completed", "workflow_completed"
    ]
    assert payloads[-1]["result"]["article"] == "正文"

@pytest.mark.asyncio
async def test_stream_sanitizes_unhandled_failures():
    payloads = await collect_payloads(failing_workflow_factory)
    assert payloads[-1]["type"] == "workflow_failed"
    assert payloads[-1]["detail"] == {"error_type": "RuntimeError"}
    assert "secret-value" not in json.dumps(payloads[-1])
```

Add an encoding test proving Unicode is preserved and literal newlines inside JSON cannot break SSE framing.

- [ ] **Step 2: Run transport tests and verify RED**

Run:

```powershell
python -m pytest tests/test_agent_event_stream.py -q
```

Expected: FAIL because `agent_event_stream.py` does not exist.

- [ ] **Step 3: Implement the queue bridge**

Implement a daemon worker and queue sentinel:

```python
async def stream_workflow_events(factory, topic, max_retries, trace_id):
    events = queue.Queue()
    stopped = threading.Event()

    def publish(event):
        if not stopped.is_set():
            events.put(event)

    def run():
        try:
            workflow = factory(event_callback=publish, trace_id=trace_id)
            result = workflow.run(topic, max_retries=max_retries)
            workflow.trace.emit(
                "workflow_completed", "workflow", "ok", result=result
            )
        except Exception as error:
            publish(build_failure_event(trace_id, error))
        finally:
            events.put(STREAM_END)

    threading.Thread(target=run, daemon=True).start()
    try:
        while True:
            event = await asyncio.to_thread(events.get)
            if event is STREAM_END:
                break
            yield encode_sse(event)
    finally:
        stopped.set()
```

Ensure callback events are enqueued once: `TraceLogger.emit()` already invokes the callback, so the final event must be emitted or published, not both.

- [ ] **Step 4: Add the FastAPI route**

Extract a small `_build_agent_workflow(event_callback=None, trace_id=None)` factory in `rag_api.py`, reuse it in the synchronous route, and add:

```python
@app.post("/agent/write/stream")
def agent_write_stream(req: AgentWriteRequest, request: Request):
    if not req.topic.strip():
        raise HTTPException(400, "主题不能为空")
    trace_id = request.headers.get(TRACE_HEADER, uuid.uuid4().hex)
    return StreamingResponse(
        stream_workflow_events(
            _build_agent_workflow, req.topic, req.max_retries, trace_id
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 5: Run focused transport tests and API import checks**

Run:

```powershell
python -m pytest tests/test_agent_event_stream.py -q
python -m compileall -q agent_event_stream.py rag_api.py rag_multiagent.py
```

Expected: tests pass and compilation exits 0.

- [ ] **Step 6: Commit Task 2**

```powershell
git add agent_event_stream.py rag_api.py tests/test_agent_event_stream.py
git commit -m "feat: stream agent workflow events over SSE"
```

---

### Task 3: Parse SSE and reduce events into reliable frontend state

**Files:**
- Create: `frontend/src/agentMonitoring.ts`
- Create: `frontend/tests/agentMonitoring.test.ts`

**Interfaces:**
- Produces: `AgentStreamParser.push(chunk: string): AgentEvent[]`, `AgentStreamParser.finish(): AgentEvent[]`.
- Produces: `createAgentMonitorState()` and `reduceAgentEvent(state, event)` returning immutable role state, metrics, timeline, review state, result, and error.

- [ ] **Step 1: Write failing parser and reducer tests**

```typescript
test("SSE parser handles split and batched frames", () => {
  const parser = new AgentStreamParser()
  assert.deepEqual(parser.push('data: {"sequence":1,"type":"agent_sta'), [])
  assert.equal(parser.push(
    'rted","trace_id":"t","timestamp":"2026-08-11T00:00:00","agent":"writer","attempt":1,"status":"running","duration_s":null,"tokens":null,"detail":{},"result":null}\n\n' +
    'data: {"sequence":2,"type":"agent_completed","trace_id":"t","timestamp":"2026-08-11T00:00:01","agent":"writer","attempt":1,"status":"ok","duration_s":1.25,"tokens":null,"detail":{},"result":null}\n\n'
  ).length, 2)
})

test("role metrics use completed events and preserve missing token usage", () => {
  let state = createAgentMonitorState()
  state = reduceAgentEvent(state, started("writer", 1))
  state = reduceAgentEvent(state, completed("writer", 1, 1.25, null))
  assert.equal(state.roles.writer.calls, 1)
  assert.equal(state.roles.writer.avgDurationS, 1.25)
  assert.equal(state.roles.writer.totalTokens, null)
})
```

Add tests for duplicate sequence suppression, review/retry state, workflow completion, and workflow failure while preserving earlier timeline events.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```powershell
Set-Location frontend
npm test
```

Expected: FAIL because `agentMonitoring.ts` does not exist.

- [ ] **Step 3: Implement the parser and reducer**

Define discriminated event types matching the backend schema. Parse only `data:` lines separated by a blank line; preserve incomplete frames across `push()` calls; reject malformed JSON with a controlled `AgentStreamParseError`.

Reducer rules:

```typescript
case "agent_started":
  return markRole(state, event.agent, "running")
case "agent_completed":
  return appendMetric(state, event, "ok")
case "agent_failed":
  return appendMetric(state, event, "fail")
case "review_completed":
  return setReview(state, event.detail)
case "retry_scheduled":
  return setRetry(state, event.attempt)
case "workflow_completed":
  return { ...state, result: event.result, completed: true }
case "workflow_failed":
  return { ...state, error: "工作流执行失败", completed: true }
```

Only completed/failed events increment calls. Average duration uses actual numeric durations. Token totals remain `null` until at least one provider-reported value exists.

- [ ] **Step 4: Run frontend tests and verify GREEN**

Run:

```powershell
npm test
```

Expected: all tests pass, including the new parser/reducer tests.

- [ ] **Step 5: Commit Task 3**

```powershell
git add frontend/src/agentMonitoring.ts frontend/tests/agentMonitoring.test.ts
git commit -m "feat: model live agent monitoring state"
```

---

### Task 4: Wire the live monitor into the writing page

**Files:**
- Modify: `frontend/src/App.tsx:1013-1111`
- Modify: `frontend/src/App.css:584-661,913-936`
- Modify: `README.md`

**Interfaces:**
- Consumes: `AgentStreamParser`, `createAgentMonitorState`, and `reduceAgentEvent` from Task 3.
- Produces: a live writing-page timeline and role cards driven exclusively by streamed events.

- [ ] **Step 1: Replace the synchronous fetch with streamed consumption**

Initialize monitor state at request start, fetch `/agent/write/stream`, and consume the body:

```typescript
const parser = new AgentStreamParser()
const reader = resp.body?.getReader()
const decoder = new TextDecoder()
while (reader) {
  const { done, value } = await reader.read()
  if (done) break
  for (const event of parser.push(decoder.decode(value, { stream: true }))) {
    setMonitor((current) => reduceAgentEvent(current, event))
  }
}
for (const event of parser.finish()) {
  setMonitor((current) => reduceAgentEvent(current, event))
}
```

Treat a stream ending without `workflow_completed` or `workflow_failed` as an explicit interruption error. Continue using `ProtectedRequestScope` for aborts.

- [ ] **Step 2: Render truthful status cards and timeline**

Always show the monitor while loading or when events exist. Each role card displays localized role name, waiting/running/success/failure, real call count, average duration, and Token total or “供应商未返回”. Render timeline rows using event type, attempt, timestamp, safe detail, and duration. Display review rating/verdict/issue count and retry transitions.

Remove the old `result.monitor.agent_metrics` rendering so the page has one source of truth.

- [ ] **Step 3: Add focused styles and usage documentation**

Add flat terminal-style state colors and an accessible `aria-live="polite"` timeline without changing the project’s dark/cyan visual language. Update README writing instructions to state that monitoring is live SSE and list the displayed real fields.

- [ ] **Step 4: Run frontend verification**

Run:

```powershell
Set-Location frontend
npm test
npm run build:check
npm run build
```

Expected: tests, TypeScript checking, and Vite production build exit 0. Existing bundle-size warnings may remain but no new errors are allowed.

- [ ] **Step 5: Commit Task 4**

```powershell
git add frontend/src/App.tsx frontend/src/App.css README.md
git commit -m "fix: show real-time agent execution data"
```

---

### Task 5: Full regression and controlled smoke verification

**Files:**
- Verify only; modify code only through a new RED/GREEN cycle if a failure exposes a defect.

**Interfaces:**
- Consumes all prior task outputs.
- Produces fresh evidence for backend behavior, frontend behavior, build integrity, and sanitized SSE output.

- [ ] **Step 1: Run the full offline backend/MCP suite**

Use the project’s established Python 3.11 test environment and exclude only the documented online integration file:

```powershell
python -m pytest tests --ignore=tests/test_api.py -q
```

Expected: all offline tests pass.

- [ ] **Step 2: Run full frontend verification**

```powershell
Set-Location frontend
npm test
npm run build:check
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 3: Run controlled SSE smoke without real model usage**

Start a one-process test app with a fake workflow factory, call `/agent/write/stream`, and verify that at least one event arrives before `workflow_completed`; assert role durations and Token usage match the fixture and scan the stream for the fixture secret.

Expected: ordered events, exact fixture metrics, no secret occurrence, and no real LLM request.

- [ ] **Step 4: Run security and diff checks**

```powershell
pre-commit run --all-files
git diff --check
git status --short
```

Expected: all configured checks pass; only the three pre-existing unrelated untracked paths remain outside committed work.
