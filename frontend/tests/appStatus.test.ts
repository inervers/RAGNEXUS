import assert from "node:assert/strict"
import test from "node:test"

import {
  qaReadinessCopy,
  rerankerDisplay,
  serviceStateFromHealth,
} from "../src/appStatus.ts"

test("health requires both an ok response and ok payload", () => {
  assert.equal(serviceStateFromHealth(true, "ok"), "online")
  assert.equal(serviceStateFromHealth(false, "ok"), "offline")
  assert.equal(serviceStateFromHealth(true, "error"), "offline")
  assert.equal(serviceStateFromHealth(true, undefined), "offline")
})

test("offline and checking readiness never claim the knowledge base is ready", () => {
  const offline = qaReadinessCopy("offline")
  const checking = qaReadinessCopy("checking")

  assert.equal(offline.kicker, "RAGNEXUS // offline")
  assert.equal(offline.title, "知识库不可用")
  assert.doesNotMatch(`${offline.kicker}${offline.title}`, /ready|就绪/i)
  assert.doesNotMatch(`${checking.kicker}${checking.title}`, /ready|就绪/i)
})

test("reranker fallback is labeled as degradation, not successful cross-encoding", () => {
  const display = rerankerDisplay({
    mode: "fallback",
    reason: "model_load_failed:OSError",
  })

  assert.deepEqual(display, {
    mode: "fallback",
    title: "Reranker（降级）",
    message: "Cross-Encoder 不可用，结果保留 Hybrid 排序（model_load_failed:OSError）",
  })
})

test("cross encoder mode is labeled as actually executed", () => {
  assert.deepEqual(rerankerDisplay({ mode: "cross_encoder", reason: null }), {
    mode: "cross_encoder",
    title: "Reranker（Cross-Encoder）",
    message: "Cross-Encoder 重排序已执行",
  })
})
