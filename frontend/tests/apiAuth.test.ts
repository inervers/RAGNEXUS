import assert from "node:assert/strict"
import test from "node:test"

import {
  ApiAuthError,
  ApiKeyRequiredError,
  ProtectedRequestScope,
  authHeaders,
  clearSessionApiKey,
  ensureApiResponse,
  readSessionApiKey,
  saveSessionApiKey,
  type KeyStorage,
} from "../src/apiAuth.ts"

function memoryStorage(): KeyStorage {
  const values = new Map<string, string>()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

test("API key is stored only through the supplied session storage", () => {
  const storage = memoryStorage()

  saveSessionApiKey(storage, "  browser-session-key-39d748cc927d4102  ")

  assert.equal(readSessionApiKey(storage), "browser-session-key-39d748cc927d4102")
  clearSessionApiKey(storage)
  assert.equal(readSessionApiKey(storage), "")
})

test("protected request headers reject an empty API key locally", () => {
  assert.throws(() => authHeaders(""), ApiKeyRequiredError)
  assert.throws(() => authHeaders("   "), ApiKeyRequiredError)
})

test("protected request headers merge content type with the session key", () => {
  assert.deepEqual(
    authHeaders("browser-session-key-39d748cc927d4102", { "Content-Type": "application/json" }),
    {
      "Content-Type": "application/json",
      "X-API-Key": "browser-session-key-39d748cc927d4102",
    },
  )
})

test("saving an empty API key is rejected instead of persisting an unusable credential", () => {
  const storage = memoryStorage()

  assert.throws(() => saveSessionApiKey(storage, ""), ApiKeyRequiredError)
  assert.equal(readSessionApiKey(storage), "")
})

test("401 and 403 responses become an explicit invalid-key error", async () => {
  for (const status of [401, 403]) {
    await assert.rejects(
      ensureApiResponse(new Response("{}", { status })),
      (error: unknown) => error instanceof ApiAuthError && error.status === status,
    )
  }
})

test("non-auth API failures remain distinguishable from invalid credentials", async () => {
  await assert.rejects(
    ensureApiResponse(new Response("boom", { status: 500 })),
    /API 请求失败（HTTP 500）/,
  )
})

test("protected request scope aborts obsolete requests on key change", () => {
  const scope = new ProtectedRequestScope()
  const first = scope.begin()
  const second = scope.begin()

  assert.equal(first.aborted, true)
  assert.equal(second.aborted, false)

  scope.abort()
  assert.equal(second.aborted, true)
})
