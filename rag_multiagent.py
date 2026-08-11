"""
rag_multiagent.py — L7 Multi-Agent 编排模块
============================================
结构化通信 + 持久化记忆 + 执行追踪。
可直接调用，也可通过 API 触发。
"""

import hashlib, json, os, time, uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional
from openai import OpenAI

from agent_contract import validate_max_retries

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass(frozen=True)
class ReviewResult:
    issues: list[str]
    rating: int
    verdict: str


def parse_review_result(review_raw) -> ReviewResult:
    fallback = ReviewResult(["审核结果格式无效"], 0, "需要修改")
    if not isinstance(review_raw, str):
        return fallback
    cleaned = review_raw.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return fallback
    if not isinstance(payload, dict):
        return fallback
    issues = payload.get("issues")
    rating = payload.get("rating")
    verdict = payload.get("verdict")
    if not isinstance(issues, list) or not all(isinstance(issue, str) for issue in issues):
        return fallback
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        return fallback
    if verdict not in {"通过", "需要修改"}:
        return fallback
    if (rating >= 4) != (verdict == "通过"):
        return fallback
    normalized_issues = [issue.strip() for issue in issues if issue.strip()]
    if verdict == "需要修改" and not normalized_issues:
        return fallback
    return ReviewResult(normalized_issues, rating, verdict)


# =============================================
# 持久化记忆
# =============================================

class AgentMemory:
    """
    Agent 持久化记忆。每个 Agent 一个 JSON 文件。
    行动前查记忆 → 行动后存记忆。
    """

    def __init__(self, agent_name: str, base_dir: str = None):
        self.agent_name = agent_name
        memory_dir = os.path.join(base_dir or BASE_DIR, "memory")
        os.makedirs(memory_dir, exist_ok=True)
        self.filepath = os.path.join(memory_dir, f"{agent_name}.json")
        self.memories: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.memories, f, ensure_ascii=False, indent=2)

    def add(self, entry: dict):
        entry["id"] = uuid.uuid4().hex[:8]
        entry["timestamp"] = datetime.now().isoformat()
        self.memories.append(entry)
        self._save()

    def query(self, task: str, top_k: int = 3) -> list[dict]:
        keywords = set(task.lower().split())
        scored = []
        for m in self.memories:
            text = (m.get("task", "") + " " + m.get("outcome", "") + " " +
                    " ".join(m.get("issues", []))).lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scored.append((score, m))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:top_k]]

    def size(self) -> int:
        return len(self.memories)


# =============================================
# 执行追踪
# =============================================

class TraceLogger:
    """记录实际执行事件，并可将脱敏事件实时交给传输层。"""

    def __init__(
        self,
        trace_id: str | None = None,
        event_callback: Callable[[dict], None] | None = None,
    ):
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.event_callback = event_callback
        self.events: list[dict] = []
        self.sequence = 0

    def emit(
        self,
        event_type: str,
        agent: str,
        status: str,
        *,
        attempt: int | None = None,
        duration_s: float | None = None,
        tokens: int | None = None,
        detail: dict | None = None,
        result: dict | None = None,
    ) -> dict:
        self.sequence += 1
        event = {
            "type": event_type,
            "trace_id": self.trace_id,
            "sequence": self.sequence,
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "attempt": attempt,
            "status": status,
            "duration_s": round(duration_s, 2) if duration_s is not None else None,
            "tokens": tokens,
            "detail": detail or {},
            "result": result,
        }
        self.events.append(event)
        if self.event_callback is not None:
            self.event_callback(event.copy())
        return event

    def summary(self) -> dict:
        from collections import defaultdict
        if not self.events:
            return {"error": "no events"}

        by_agent = defaultdict(list)
        metric_events = [
            event
            for event in self.events
            if event["type"] in {"agent_completed", "agent_failed"}
            and event["agent"] in {"researcher", "writer", "reviewer"}
        ]
        for e in metric_events:
            by_agent[e["agent"]].append(e)

        agent_metrics = {}
        for agent, evts in by_agent.items():
            durations = [
                e["duration_s"] for e in evts if e["duration_s"] is not None
            ]
            success = [e for e in evts if e["type"] == "agent_completed"]
            known_tokens = [e["tokens"] for e in evts if e["tokens"] is not None]
            agent_metrics[agent] = {
                "calls": len(evts),
                "success": len(success),
                "avg_duration_s": round(sum(durations) / len(durations), 2) if durations else 0,
                "total_duration_s": round(sum(durations), 2),
                "total_tokens": sum(known_tokens) if known_tokens else None,
            }

        bottleneck = max(
            agent_metrics.items(), key=lambda x: x[1]["avg_duration_s"]
        )[0] if agent_metrics else None

        return {
            "trace_id": self.trace_id,
            "total_events": len(self.events),
            "agent_metrics": dict(agent_metrics),
            "bottleneck": bottleneck,
        }


# =============================================
# Multi-Agent 工作流
# =============================================

class MultiAgentWorkflow:
    """
    Researcher → Writer → Reviewer
    带持久化记忆 + 执行追踪。

    支持注入知识库搜索函数，让研究员基于真实文档输出研究结论。

    注意：使用 OpenAI 兼容 API（DeepSeek / 其他）。
    """

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-v4-flash",
                 knowledge_fn=None, event_callback=None, trace_id: str | None = None):
        """
        knowledge_fn: 可选的检索函数。
            签名: fn(query: str, top_k: int) -> list[dict]
            返回: [{"text": "...", "id": "...", "rrf_score": ...}, ...]
            传 None 时研究员用 LLM 自有知识。
        """
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.trace = TraceLogger(trace_id=trace_id, event_callback=event_callback)
        self.knowledge_fn = knowledge_fn

    def _call_llm(self, system: str, user: str,
                  temperature: float = 0.3, *, agent: str = "llm",
                  attempt: int | None = None,
                  event_detail: dict | None = None) -> str:
        start = time.time()
        self.trace.emit(
            "agent_started", agent, "running", attempt=attempt,
            detail=event_detail,
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                temperature=temperature,
                max_tokens=2048
            )
            result = resp.choices[0].message.content
            usage = getattr(resp, "usage", None)
            tokens = getattr(usage, "total_tokens", None) if usage else None
            self.trace.emit(
                "agent_completed", agent, "ok", attempt=attempt,
                duration_s=time.time() - start, tokens=tokens,
                detail=event_detail,
            )
            return result
        except Exception as e:
            self.trace.emit(
                "agent_failed", agent, "fail", attempt=attempt,
                duration_s=time.time() - start,
                detail={"error_type": type(e).__name__},
            )
            raise

    def run(self, topic: str, max_retries: int = 2,
            api_key_field: str = "") -> dict:
        """
        运行完整的 Multi-Agent 写作流水线。

        返回：
            {
                "topic": "...",
                "passed": True/False,
                "rating": int,
                "attempts": int,
                "duration_s": float,
                "article": "...",
                "trace_id": "...",
                "monitor": {...},
                "memory_sizes": {...}
            }
        """
        max_retries = validate_max_retries(max_retries)
        start = time.time()

        # 初始化记忆
        researcher_mem = AgentMemory("researcher")
        writer_mem = AgentMemory("writer")
        reviewer_mem = AgentMemory("reviewer")

        # === 研究员：先查知识库，再产出研究结论 ===
        kb_docs = []
        if self.knowledge_fn:
            try:
                kb_docs = self.knowledge_fn(topic, top_k=5)
            except Exception:
                kb_docs = []

        kb_context = ""
        if kb_docs:
            kb_context = "\n\n以下是从知识库检索到的相关文档：\n" + "\n".join(
                f"[文档 {i+1}] {d['text'][:300]}" for i, d in enumerate(kb_docs)
            )

        research = self._call_llm(
            "你是研究员。输出 JSON：{\"key_points\": [\"...\"], \"confidence\": 0-1}",
            f"研究：{topic}\n请基于知识库内容（如有）和你的知识综合分析。{kb_context}",
            temperature=0.1, agent="researcher",
            event_detail={"kb_docs": len(kb_docs)},
        )
        researcher_mem.add({"task": topic, "outcome": (research or "")[:200],
                           "role": "research", "kb_docs": len(kb_docs)})

        # === 写作 + 审核循环 ===
        article = ""
        final_rating = 0
        passed = False
        review_feedback: list[str] = []

        for attempt in range(1, max_retries + 2):
            # 查记忆：之前为什么被驳回
            mem_context = ""
            mems = writer_mem.query(topic)
            if mems:
                mem_context = "\n\n历史反馈：\n" + "\n".join(
                    f"- {m.get('outcome', '')[:100]}" for m in mems
                )
            feedback_context = ""
            if review_feedback:
                feedback_context = "\n\n上一轮审核反馈（逐项修改）：\n" + "\n".join(
                    f"- {issue}" for issue in review_feedback
                )

            article = self._call_llm(
                "你是科普写作者。输出 JSON：{\"title\": \"...\", \"content\": \"...\", \"word_count\": 0}"
                + (f"\n\n这是第 {attempt} 次修改，请改进之前的不足。" if attempt > 1 else ""),
                f"主题：{topic}\n研究资料：{research or ''}\n"
                + (f"知识库来源：{kb_context}\n" if kb_context else "")
                + f"{mem_context}{feedback_context}",
                temperature=0.4, agent="writer", attempt=attempt,
            ) or ""
            writer_mem.add({"task": f"写作{topic}第{attempt}稿",
                           "outcome": article[:200], "round": attempt})

            # 审核
            review_raw = self._call_llm(
                "你是严格的内容审核员。输出 JSON：{\"issues\": [...], \"rating\": 1-5, \"verdict\": \"通过/需要修改\"}\n"
                "评分低于 4 必须输出需要修改。",
                f"审核文章：\n{article[:1500]}\n\n参考：{research}",
                temperature=0.1, agent="reviewer", attempt=attempt,
            )

            # 解析审核结果
            review = parse_review_result(review_raw)
            final_rating = review.rating
            verdict = review.verdict
            review_feedback = review.issues
            self.trace.emit(
                "review_completed", "reviewer", "ok", attempt=attempt,
                detail={
                    "rating": final_rating,
                    "verdict": verdict,
                    "issue_count": len(review_feedback),
                },
            )

            reviewer_mem.add({
                "task": f"审核{topic}第{attempt}稿",
                "outcome": f"评分{final_rating}，裁决{verdict}",
                "rating": final_rating,
                "issues": review_feedback
            })

            # 通过判定：绝对达标或相对改进
            if verdict == "通过" or final_rating >= 4:
                passed = True
                break

            if attempt > max_retries:
                break
            self.trace.emit(
                "retry_scheduled", "reviewer", "ok", attempt=attempt,
                detail={
                    "next_attempt": attempt + 1,
                    "issue_count": len(review_feedback),
                    "feedback_sha256": hashlib.sha256(
                        "\n".join(review_feedback).encode("utf-8")
                    ).hexdigest()[:16],
                },
            )

        elapsed = round(time.time() - start, 1)

        # 监控摘要
        monitor = self.trace.summary()

        return {
            "topic": topic,
            "passed": passed,
            "rating": final_rating,
            "verdict": verdict,
            "attempts": attempt,
            "duration_s": elapsed,
            "article": article[:5000],
            "trace_id": self.trace.trace_id,
            "monitor": monitor,
            "kb_docs": len(kb_docs) if kb_docs else 0,
            "memory_sizes": {
                "researcher": researcher_mem.size(),
                "writer": writer_mem.size(),
                "reviewer": reviewer_mem.size(),
            }
        }


# =============================================
# 快速验证
# =============================================

if __name__ == "__main__":
    import os
    key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ZHIPU_API_KEY")
           or os.environ.get("OPENAI_API_KEY"))
    if not key:
        print("需要设置 DEEPSEEK_API_KEY（推荐）或 ZHIPU_API_KEY")
        exit(1)

    wf = MultiAgentWorkflow(api_key=key)
    result = wf.run("多层感知机的反向传播", max_retries=1)
    print(f"\n主题: {result['topic']}")
    print(f"结果: {'✓ 通过' if result['passed'] else '✗ 未通过'}  |  "
          f"评分: {result['rating']}/5  |  尝试: {result['attempts']} 次")
    print(f"耗时: {result['duration_s']}s")
    print(f"追踪 ID: {result['trace_id']}")
    print(f"监控: {result['monitor']}")
