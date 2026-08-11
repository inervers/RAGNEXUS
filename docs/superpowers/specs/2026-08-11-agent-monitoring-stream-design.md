# Agent 写作实时监控设计

## 目标

将当前写作页在任务结束后展示的聚合卡片，改为由后端真实执行事件驱动的实时监控。Researcher、Writer、Reviewer 的状态、耗时、Token、知识库命中数、审核结果和重试原因都必须来自实际执行过程，不再用执行前写入的 `ok` 与零耗时充当角色指标。

## 当前问题

- `POST /agent/write` 是同步接口，前端只能在完整流程结束后拿到结果。
- Researcher、Writer、Reviewer 的步骤日志在实际工作开始前就标记为成功，持续时间默认为零。
- 所有真实 LLM 调用都归到通用 `llm` 角色，无法计算角色级耗时与 Token。
- `TraceLogger.summary()` 只返回聚合值，不返回事件明细，前端无法呈现真实时间线。

## 方案选择

采用 Server-Sent Events（SSE）。RAGNEXUS 已使用 `StreamingResponse` 处理 `/query/stream`，SSE 能复用现有 FastAPI 和前端流读取方式，且写作监控只需要服务器向浏览器单向推送。

不采用轮询，因为需要额外的后台任务存储、任务 ID 和状态清理；不采用 WebSocket，因为当前不存在客户端向执行中的工作流持续发送控制消息的需求。

## 后端架构

### 工作流事件

`MultiAgentWorkflow` 接收可选事件回调。每个事件使用统一结构：

```json
{
  "type": "agent_started | agent_completed | agent_failed | review_completed | retry_scheduled | workflow_completed | workflow_failed",
  "trace_id": "string",
  "sequence": 1,
  "timestamp": "ISO-8601",
  "agent": "researcher | writer | reviewer | workflow",
  "attempt": 1,
  "status": "running | ok | fail",
  "duration_s": 0.0,
  "tokens": 0,
  "detail": {},
  "result": null
}
```

字段约束：

- `sequence` 在单次工作流中严格递增。
- `duration_s` 只在完成或失败事件中出现，来自实际调用计时。
- `tokens` 来自模型响应 usage；供应商不返回 usage 时为 `null`，不得伪造为零。
- `detail` 只放结构化、安全字段，例如 `kb_docs`、`rating`、`issue_count`、`verdict`，不返回 API Key、完整 Prompt、知识库原文或模型异常全文。
- `workflow_completed` 的 `result` 与现有 `/agent/write` 的结果结构兼容。

### 角色归属与计时

`_call_llm` 增加 `agent` 和 `attempt` 参数。调用开始时发出 `agent_started`，模型返回后发出 `agent_completed`；异常时发出 `agent_failed` 后继续抛出。耗时覆盖真实模型调用，不把 Prompt 构建时间伪装为模型耗时。

Researcher 的知识库检索结果作为其完成事件的 `kb_docs` 字段返回。Reviewer 解析完成后额外发出 `review_completed`，包含实际评分、裁决和问题数量。需要重写时发出 `retry_scheduled`。

### SSE 接口

新增 `POST /agent/write/stream`：

- 沿用 `AgentWriteRequest`、`X-API-Key` 鉴权、限流和 `X-Trace-Id`。
- 使用后台线程运行同步工作流，通过线程安全队列把事件交给异步生成器。
- 每条消息使用 `data: <JSON>\n\n` 格式，响应类型为 `text/event-stream`。
- 正常结束一定发送一次 `workflow_completed`。
- 未处理异常转为脱敏后的 `workflow_failed`，随后结束流。
- 客户端断开时停止继续向队列写入；本次实现不强制中断已经发出的上游 LLM 请求。
- 保留原有 `POST /agent/write`，保证旧调用不受影响。

## 前端设计

写作页改为调用 `/agent/write/stream`，复用现有 `fetch + ReadableStream` 解析模式。

页面维护：

- 事件时间线：按 `sequence` 去重并排序。
- 角色状态：Researcher、Writer、Reviewer 当前处于等待、执行、成功或失败。
- 真实指标：按完成/失败事件计算调用次数、成功数、实际平均耗时和 Token；Token 缺失时显示“供应商未返回”。
- 审核信息：显示当前轮次、评分、裁决、问题数量和是否进入下一轮。
- 最终结果：收到 `workflow_completed` 后继续展示文章、评分、尝试次数和总耗时。

网络中断、非法 SSE JSON 或 `workflow_failed` 都进入可见错误状态；已经收到的事件保留，便于定位失败阶段。用户切换 API Key、离开页面或重新开始任务时，通过现有 AbortController 取消前端读取。

## 兼容性与边界

- 不改变最大重试范围及审核通过规则。
- 不改变现有文章 JSON 格式与同步接口响应格式。
- 不新增数据库或任务队列。
- 不实现暂停、恢复或强制取消正在进行的 LLM 请求。
- 不把监控功能描述成分布式 tracing；它是单进程工作流的结构化执行事件流。

## 测试与验收

### 后端

- 事件顺序与 `sequence` 单调递增。
- 三个角色的完成事件带真实非负耗时，并正确归属 Token。
- Reviewer 的评分、问题数量和重试事件与工作流结果一致。
- LLM 异常产生角色失败事件和最终工作流失败事件，且不泄露敏感字符串。
- SSE 接口逐条输出事件，正常流程以 `workflow_completed` 结束。
- 原有同步 `/agent/write` 行为保持兼容。

### 前端

- SSE 分片跨行、单次多事件和最后残留缓冲均可正确解析。
- 重复 sequence 不会生成重复时间线项。
- 收到开始、完成、审核、重试和失败事件时，角色状态与指标正确更新。
- Token 为 `null` 时不显示虚假的 `0`。
- `workflow_completed` 正确恢复现有文章结果展示。

### 完成标准

- 写作执行期间页面能逐步看到真实事件，而不是只显示固定 loading 文案。
- Researcher、Writer、Reviewer 的成功率和耗时来自实际执行结果。
- 后端测试、前端测试、TypeScript 检查和 Vite 构建全部通过。
- 使用受控的假 LLM 响应完成一轮端到端 SSE smoke，不消耗真实模型额度。
