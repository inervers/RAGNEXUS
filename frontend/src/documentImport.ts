export interface SelectedDocumentFile {
  filename: string
  encodedContent: string
  title: string
  preview: string
  fullLength: number
  truncated: boolean
}

export function buildImportRequest(selected: SelectedDocumentFile) {
  return {
    filename: selected.filename,
    content: selected.encodedContent,
  }
}
