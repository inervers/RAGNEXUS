export type AgentRole = "researcher" | "writer" | "reviewer"
export type AgentName = AgentRole | "workflow"
export type AgentEventType =
  | "agent_started"
  | "agent_completed"
  | "agent_failed"
  | "review_completed"
  | "retry_scheduled"
  | "workflow_completed"
  | "workflow_failed"

export interface AgentWorkflowResult {
  article?: string
  attempts?: number
  duration_s?: number
  passed?: boolean
  rating?: number
  verdict?: string
  [key: string]: unknown
}

export interface AgentEvent {
  type: AgentEventType
  trace_id: string
  sequence: number
  timestamp: string
  agent: AgentName
  attempt: number | null
  status: "running" | "ok" | "fail"
  duration_s: number | null
  tokens: number | null
  detail: Record<string, unknown>
  result: AgentWorkflowResult | null
}

export class AgentStreamParseError extends Error {
  constructor() {
    super("Agent 事件流格式无效")
    this.name = "AgentStreamParseError"
  }
}

function isAgentEvent(value: unknown): value is AgentEvent {
  if (!value || typeof value !== "object") return false
  const event = value as Partial<AgentEvent>
  return (
    typeof event.type === "string" &&
    typeof event.trace_id === "string" &&
    typeof event.sequence === "number" &&
    typeof event.timestamp === "string" &&
    typeof event.agent === "string" &&
    typeof event.status === "string" &&
    typeof event.detail === "object"
  )
}

function parseFrame(frame: string): AgentEvent[] {
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n")
  if (!data) return []
  try {
    const value: unknown = JSON.parse(data)
    if (!isAgentEvent(value)) throw new AgentStreamParseError()
    return [value]
  } catch (error) {
    if (error instanceof AgentStreamParseError) throw error
    throw new AgentStreamParseError()
  }
}

export class AgentStreamParser {
  private buffer = ""

  push(chunk: string): AgentEvent[] {
    this.buffer += chunk
    const events: AgentEvent[] = []
    while (true) {
      const separator = this.buffer.match(/\r?\n\r?\n/)
      if (!separator || separator.index === undefined) break
      const frame = this.buffer.slice(0, separator.index)
      this.buffer = this.buffer.slice(separator.index + separator[0].length)
      events.push(...parseFrame(frame))
    }
    return events
  }

  finish(): AgentEvent[] {
    const frame = this.buffer.trim()
    this.buffer = ""
    return frame ? parseFrame(frame) : []
  }
}

export interface AgentRoleMetrics {
  status: "waiting" | "running" | "success" | "failed"
  calls: number
  success: number
  totalDurationS: number
  avgDurationS: number
  totalTokens: number | null
}

export interface AgentReviewState {
  attempt: number
  rating: number
  verdict: string
  issueCount: number
  nextAttempt: number | null
}

export interface AgentMonitorState {
  roles: Record<AgentRole, AgentRoleMetrics>
  timeline: AgentEvent[]
  review: AgentReviewState | null
  result: AgentWorkflowResult | null
  error: string | null
  completed: boolean
  seenSequences: ReadonlySet<number>
}

function emptyRole(): AgentRoleMetrics {
  return {
    status: "waiting",
    calls: 0,
    success: 0,
    totalDurationS: 0,
    avgDurationS: 0,
    totalTokens: null,
  }
}

export function createAgentMonitorState(): AgentMonitorState {
  return {
    roles: {
      researcher: emptyRole(),
      writer: emptyRole(),
      reviewer: emptyRole(),
    },
    timeline: [],
    review: null,
    result: null,
    error: null,
    completed: false,
    seenSequences: new Set<number>(),
  }
}

function isRole(agent: AgentName): agent is AgentRole {
  return agent === "researcher" || agent === "writer" || agent === "reviewer"
}

function updateRole(
  state: AgentMonitorState,
  roleName: AgentRole,
  event: AgentEvent,
): AgentMonitorState {
  const role = state.roles[roleName]
  if (event.type === "agent_started") {
    return {
      ...state,
      roles: { ...state.roles, [roleName]: { ...role, status: "running" } },
    }
  }
  if (event.type !== "agent_completed" && event.type !== "agent_failed") {
    return state
  }
  const duration = typeof event.duration_s === "number" ? event.duration_s : 0
  const calls = role.calls + 1
  const totalDurationS = role.totalDurationS + duration
  const totalTokens = typeof event.tokens === "number"
    ? (role.totalTokens ?? 0) + event.tokens
    : role.totalTokens
  return {
    ...state,
    roles: {
      ...state.roles,
      [roleName]: {
        status: event.type === "agent_completed" ? "success" : "failed",
        calls,
        success: role.success + (event.type === "agent_completed" ? 1 : 0),
        totalDurationS,
        avgDurationS: Math.round((totalDurationS / calls) * 100) / 100,
        totalTokens,
      },
    },
  }
}

function numberDetail(detail: Record<string, unknown>, key: string): number {
  return typeof detail[key] === "number" ? detail[key] : 0
}

export function reduceAgentEvent(
  state: AgentMonitorState,
  event: AgentEvent,
): AgentMonitorState {
  if (state.seenSequences.has(event.sequence)) return state
  const seenSequences = new Set(state.seenSequences)
  seenSequences.add(event.sequence)
  let next: AgentMonitorState = {
    ...state,
    seenSequences,
    timeline: [...state.timeline, event].sort((a, b) => a.sequence - b.sequence),
  }

  if (isRole(event.agent)) next = updateRole(next, event.agent, event)

  if (event.type === "review_completed") {
    next = {
      ...next,
      review: {
        attempt: event.attempt ?? 0,
        rating: numberDetail(event.detail, "rating"),
        verdict: typeof event.detail.verdict === "string" ? event.detail.verdict : "未知",
        issueCount: numberDetail(event.detail, "issue_count"),
        nextAttempt: null,
      },
    }
  } else if (event.type === "retry_scheduled") {
    next = {
      ...next,
      review: next.review
        ? { ...next.review, nextAttempt: numberDetail(event.detail, "next_attempt") }
        : next.review,
    }
  } else if (event.type === "workflow_completed") {
    next = { ...next, completed: true, result: event.result }
  } else if (event.type === "workflow_failed") {
    const errorType = typeof event.detail.error_type === "string"
      ? event.detail.error_type
      : "UnknownError"
    next = {
      ...next,
      completed: true,
      error: `工作流执行失败（${errorType}）`,
    }
  }
  return next
}
