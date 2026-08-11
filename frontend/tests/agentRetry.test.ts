import assert from "node:assert/strict"
import test from "node:test"

import {
  AGENT_RETRY_MAX,
  AGENT_RETRY_MIN,
  normalizeAgentRetry,
} from "../src/agentRetry.ts"

test("agent retry input follows the backend zero-to-three contract", () => {
  assert.equal(AGENT_RETRY_MIN, 0)
  assert.equal(AGENT_RETRY_MAX, 3)
  assert.equal(normalizeAgentRetry(-1), 0)
  assert.equal(normalizeAgentRetry(2.8), 2)
  assert.equal(normalizeAgentRetry(4), 3)
})
