export interface SelectedDocumentFile {
  filename: string
  encodedContent: string
  title: string
  preview: string
  fullLength: number
  truncated: boolean
}

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

export class FileSelectionGuard {
  private generation = 0

  begin() {
    this.generation += 1
    return this.generation
  }

  invalidate() {
    this.generation += 1
  }

  isCurrent(generation: number) {
    return generation === this.generation
  }
}

export function validateSelectedFile(file: { name: string; size: number }): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase()
  if (extension !== "pdf" && extension !== "txt") return "仅支持 PDF/TXT 文件"
  if (file.size > MAX_UPLOAD_BYTES) return "文件不能超过 10 MiB"
  return null
}

export function buildImportRequest(selected: SelectedDocumentFile) {
  return {
    filename: selected.filename,
    content: selected.encodedContent,
  }
}
