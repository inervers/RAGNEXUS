const SESSION_API_KEY = "ragnexus_api_key"

export interface KeyStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

export class ApiKeyRequiredError extends Error {
  constructor() {
    super("请先在侧边栏配置 API Key")
    this.name = "ApiKeyRequiredError"
  }
}

export function readSessionApiKey(storage: KeyStorage): string {
  return storage.getItem(SESSION_API_KEY)?.trim() ?? ""
}

export function saveSessionApiKey(storage: KeyStorage, apiKey: string): string {
  const normalized = apiKey.trim()
  if (!normalized) throw new ApiKeyRequiredError()
  storage.setItem(SESSION_API_KEY, normalized)
  return normalized
}

export function clearSessionApiKey(storage: KeyStorage): void {
  storage.removeItem(SESSION_API_KEY)
}

export function authHeaders(
  apiKey: string,
  extra: Record<string, string> = {},
): Record<string, string> {
  const normalized = apiKey.trim()
  if (!normalized) throw new ApiKeyRequiredError()
  return { ...extra, "X-API-Key": normalized }
}
