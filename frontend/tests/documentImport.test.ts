import assert from "node:assert/strict"
import test from "node:test"

import {
  FileSelectionGuard,
  buildImportRequest,
  validateSelectedFile,
  type SelectedDocumentFile,
} from "../src/documentImport.ts"


test("import request uses original encoded file instead of truncated preview", () => {
  const selected: SelectedDocumentFile = {
    filename: "long.txt",
    encodedContent: "FULL_BASE64",
    title: "long",
    preview: "CUT_PREVIEW",
    fullLength: 6001,
    truncated: true,
  }

  assert.deepEqual(buildImportRequest(selected), {
    filename: "long.txt",
    content: "FULL_BASE64",
  })
})


test("newer file selection invalidates every older async completion", () => {
  const guard = new FileSelectionGuard()
  const first = guard.begin()
  const second = guard.begin()

  assert.equal(guard.isCurrent(first), false)
  assert.equal(guard.isCurrent(second), true)
  guard.invalidate()
  assert.equal(guard.isCurrent(second), false)
})


test("file validation rejects unsupported and oversized selections", () => {
  assert.equal(validateSelectedFile({ name: "notes.md", size: 12 }), "仅支持 PDF/TXT 文件")
  assert.match(validateSelectedFile({ name: "large.txt", size: 10 * 1024 * 1024 + 1 }) ?? "", /10 MiB/)
  assert.equal(validateSelectedFile({ name: "safe.txt", size: 1024 }), null)
})
