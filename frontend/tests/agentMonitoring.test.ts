import assert from "node:assert/strict"
import test from "node:test"

import {
  AgentStreamParser,
  createAgentMonitorState,
  reduceAgentEvent,
  type AgentEvent,
} from "../src/agentMonitoring.ts"


function event(
  sequence: number,
  type: AgentEvent["type"],
  overrides: Partial<AgentEvent> = {},
): AgentEvent {
  return {
    type,
    trace_id: "trace-1",
    sequence,
    timestamp: `2026-08-11T00:00:0${sequence}`,
    agent: "writer",
    attempt: 1,
    status: type === "agent_started" ? "running" : "ok",
    duration_s: null,
    tokens: null,
    detail: {},
    result: null,
    ...overrides,
  } as AgentEvent
}


function frame(value: AgentEvent): string {
  return `data: ${JSON.stringify(value)}\n\n`
}


test("SSE parser handles frames split across chunks and batched together", () => {
  const parser = new AgentStreamParser()
  const first = frame(event(1, "agent_started"))
  const second = frame(event(2, "agent_completed", { duration_s: 1.25 }))

  assert.deepEqual(parser.push(first.slice(0, 19)), [])
  const parsed = parser.push(first.slice(19) + second)

  assert.equal(parsed.length, 2)
  assert.equal(parsed[0].sequence, 1)
  assert.equal(parsed[1].duration_s, 1.25)
})


test("SSE parser flushes a final frame without a trailing blank line", () => {
  const parser = new AgentStreamParser()
  const last = frame(event(3, "workflow_completed", {
    agent: "workflow",
    result: { article: "正文" },
  })).trimEnd()

  assert.deepEqual(parser.push(last), [])
  assert.equal(parser.finish()[0].result?.article, "正文")
})


test("duplicate sequences do not create duplicate timeline or metrics", () => {
  const completed = event(2, "agent_completed", {
    duration_s: 2,
    tokens: 30,
  })
  let state = createAgentMonitorState()

  state = reduceAgentEvent(state, completed)
  state = reduceAgentEvent(state, completed)

  assert.equal(state.timeline.length, 1)
  assert.equal(state.roles.writer.calls, 1)
  assert.equal(state.roles.writer.totalTokens, 30)
})


test("role metrics use actual completion data and preserve unknown token usage", () => {
  let state = createAgentMonitorState()
  state = reduceAgentEvent(state, event(1, "agent_started"))
  state = reduceAgentEvent(state, event(2, "agent_completed", {
    duration_s: 1.25,
    tokens: null,
  }))

  assert.equal(state.roles.writer.status, "success")
  assert.equal(state.roles.writer.calls, 1)
  assert.equal(state.roles.writer.success, 1)
  assert.equal(state.roles.writer.avgDurationS, 1.25)
  assert.equal(state.roles.writer.totalTokens, null)
})


test("review and retry events expose the real decision", () => {
  let state = createAgentMonitorState()
  state = reduceAgentEvent(state, event(4, "review_completed", {
    agent: "reviewer",
    detail: { rating: 2, verdict: "需要修改", issue_count: 1 },
  }))
  state = reduceAgentEvent(state, event(5, "retry_scheduled", {
    agent: "reviewer",
    detail: { next_attempt: 2, issue_count: 1 },
  }))

  assert.deepEqual(state.review, {
    attempt: 1,
    rating: 2,
    verdict: "需要修改",
    issueCount: 1,
    nextAttempt: 2,
  })
})


test("workflow failure preserves earlier events and exposes a safe error", () => {
  let state = createAgentMonitorState()
  state = reduceAgentEvent(state, event(1, "agent_started", {
    agent: "researcher",
  }))
  state = reduceAgentEvent(state, event(2, "workflow_failed", {
    agent: "workflow",
    status: "fail",
    detail: { error_type: "RuntimeError" },
  }))

  assert.equal(state.timeline.length, 2)
  assert.equal(state.completed, true)
  assert.equal(state.error, "工作流执行失败（RuntimeError）")
})
