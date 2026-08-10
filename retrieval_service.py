"""统一检索服务：隔离 strategy/config、结果选择与 trace 契约。"""

from dataclasses import dataclass
from typing import Callable, Optional


VALID_STRATEGIES = {"dense", "hybrid", "reranked"}

GENERATION_SYSTEM_PROMPT = (
    "你是一个基于知识库上下文回答问题的 AI 助手。\n"
    "相关知识片段已提供在用户消息中，不要再次检索。\n"
    "可用工具仅用于添加文档、摘要和翻译。\n"
    "回答必须区分资料中的事实与无法确认的信息，并使用与用户相同的语言。"
)


@dataclass(frozen=True)
class RetrievalConfig:
    strategy: str = "hybrid"
    top_k: int = 6
    dense_weight: float = 1.0
    sparse_weight: float = 2.0

    def __post_init__(self):
        if self.strategy not in VALID_STRATEGIES:
            raise ValueError(f"不支持的 retrieval strategy: {self.strategy}")
        if not isinstance(self.top_k, int) or not 1 <= self.top_k <= 50:
            raise ValueError("top_k 必须是 1..50 的整数")
        if self.dense_weight <= 0:
            raise ValueError("dense_weight 必须大于 0")
        if self.sparse_weight <= 0:
            raise ValueError("sparse_weight 必须大于 0")


class RetrievalService:
    """通过 provider 复用现有 HybridSearch/Reranker，便于离线契约测试。"""

    def __init__(
        self,
        search_provider: Callable[[], object],
        rerank_provider: Optional[Callable[[str, list[dict], int], tuple[list[dict], dict]]] = None,
        corpus_version_provider: Optional[Callable[[], object]] = None,
    ):
        self._search_provider = search_provider
        self._rerank_provider = rerank_provider
        self._corpus_version_provider = corpus_version_provider or (lambda: None)

    def retrieve(
        self,
        query: str,
        config: RetrievalConfig,
        trace_id: str,
    ) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 必须是非空字符串")
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise ValueError("trace_id 必须是非空字符串")

        raw = self._search_provider().search(
            query=query,
            top_k=config.top_k,
            dense_weight=config.dense_weight,
            sparse_weight=config.sparse_weight,
        )
        if not isinstance(raw, dict):
            raise ValueError("search provider 必须返回字典")

        result = dict(raw)
        reranker_mode = None
        if config.strategy == "dense":
            selected = result.get("dense_top", [])
        elif config.strategy == "hybrid":
            selected = result.get("hybrid_top", [])
        else:
            if self._rerank_provider is None:
                raise ValueError("reranked strategy 缺少 rerank provider")
            candidates = result.get("hybrid_top", [])
            selected, reranker_status = self._rerank_provider(
                query, candidates, config.top_k
            )
            result["reranked"] = selected
            result["reranker_status"] = reranker_status
            reranker_mode = reranker_status.get("mode")

        if not isinstance(selected, list):
            raise ValueError("selected retrieval result 必须是列表")
        result["selected"] = selected[: config.top_k]
        result["trace"] = {
            "trace_id": trace_id,
            "strategy": config.strategy,
            "top_k": config.top_k,
            "dense_weight": config.dense_weight,
            "sparse_weight": config.sparse_weight,
            "corpus_version": self._corpus_version_provider(),
            "reranker_mode": reranker_mode,
        }
        return result


def _selected_chunks(retrieval_result):
    chunks = retrieval_result.get("selected", [])
    if not isinstance(chunks, list):
        raise ValueError("retrieval_result.selected 必须是列表")
    return chunks


def build_generation_context(question: str, retrieval_result: dict) -> str:
    """把统一 selected chunks 转成生成层唯一上下文。"""
    parts = ["## 知识库检索结果（请仅基于相关资料回答）"]
    for chunk in _selected_chunks(retrieval_result):
        parts.append(f"[{chunk.get('id', '?')}] {chunk.get('text', '')}")
    parts.append(f"## 用户问题\n{question}")
    return "\n\n".join(parts)


def build_sources(question: str, retrieval_result: dict) -> list[dict]:
    """保留 selected 的 ID/顺序，兼容前端 query/content 字段。"""
    return [
        {
            "id": chunk.get("id", ""),
            "query": question[:80],
            "content": chunk.get("text", "")[:300],
        }
        for chunk in _selected_chunks(retrieval_result)
    ]


def without_retrieval_tool(tools: list[dict]) -> list[dict]:
    """生成阶段已有显式 context，不再允许同一请求二次检索。"""
    return [
        tool
        for tool in tools
        if tool.get("function", {}).get("name") != "search_knowledge"
    ]


def format_trace_summary(retrieval_result: dict) -> str:
    trace = retrieval_result.get("trace", {})
    return (
        f"trace_id={trace.get('trace_id', '?')} "
        f"strategy={trace.get('strategy', '?')} "
        f"top_k={trace.get('top_k', '?')} "
        f"corpus_version={trace.get('corpus_version', '?')}"
    )
