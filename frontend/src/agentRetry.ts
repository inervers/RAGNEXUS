export const AGENT_RETRY_MIN = 0
export const AGENT_RETRY_MAX = 3

export function normalizeAgentRetry(value: number): number {
  if (!Number.isFinite(value)) return AGENT_RETRY_MIN
  return Math.min(AGENT_RETRY_MAX, Math.max(AGENT_RETRY_MIN, Math.trunc(value)))
}
