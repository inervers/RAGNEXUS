import assert from "node:assert/strict"
import test from "node:test"

import {
  ApiKeyRequiredError,
  authHeaders,
  clearSessionApiKey,
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
