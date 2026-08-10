export type ServiceState = "checking" | "online" | "offline"

export interface RerankerStatus {
  mode: "cross_encoder" | "fallback"
  reason?: string | null
}

export function serviceStateFromHealth(
  responseOk: boolean,
  payloadStatus: unknown,
): ServiceState {
  return responseOk && payloadStatus === "ok" ? "online" : "offline"
}

export function qaReadinessCopy(state: ServiceState) {
  if (state === "online") {
    return {
      kicker: "RAGNEXUS // ready",
      title: "知识库就绪",
      subtitle: "输入问题开始对话",
    }
  }
  if (state === "offline") {
    return {
      kicker: "RAGNEXUS // offline",
      title: "知识库不可用",
      subtitle: "请先启动后端服务并检查鉴权配置",
    }
  }
  return {
    kicker: "RAGNEXUS // checking",
    title: "正在检查知识库",
    subtitle: "正在连接后端服务",
  }
}

export function rerankerDisplay(status?: RerankerStatus) {
  if (!status) return null
  if (status.mode === "fallback") {
    const reason = status.reason ? `（${status.reason}）` : ""
    return {
      mode: "fallback" as const,
      title: "Reranker（降级）",
      message: `Cross-Encoder 不可用，结果保留 Hybrid 排序${reason}`,
    }
  }
  return {
    mode: "cross_encoder" as const,
    title: "Reranker（Cross-Encoder）",
    message: "Cross-Encoder 重排序已执行",
  }
}
