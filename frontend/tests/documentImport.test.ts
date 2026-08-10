import assert from "node:assert/strict"
import test from "node:test"

import { buildImportRequest, type SelectedDocumentFile } from "../src/documentImport.ts"


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
