const SESSION_API_KEY = "ragnexus_api_key" // pragma: allowlist secret -- storage field name, not a credential

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

export class ApiAuthError extends Error {
  readonly status: number

  constructor(status: number) {
    super(status === 401 ? "API Key 缺失，请重新配置" : "API Key 无效，请重新配置")
    this.name = "ApiAuthError"
    this.status = status
  }
}

export class ProtectedRequestScope {
  private controller: AbortController | null = null

  begin(): AbortSignal {
    this.abort()
    this.controller = new AbortController()
    return this.controller.signal
  }

  abort(): void {
    this.controller?.abort()
    this.controller = null
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

export async function ensureApiResponse(response: Response): Promise<Response> {
  if (response.status === 401 || response.status === 403) {
    throw new ApiAuthError(response.status)
  }
  if (!response.ok) {
    throw new Error(`API 请求失败（HTTP ${response.status}）`)
  }
  return response
}
