import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module(filename):
    return ast.parse((ROOT / filename).read_text(encoding="utf-8"))


def _function(tree, name):
    return next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def _named_reference_count(node, name):
    return sum(
        1
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Load)
        and child.id == name
    )


def test_all_api_retrieval_adapters_call_shared_retrieve_once():
    tree = _module("rag_api.py")

    for function_name in ("query", "query_stream", "hybrid_query", "_kb_search"):
        assert _named_reference_count(_function(tree, function_name), "_retrieve") == 1


def test_rag_api_has_no_direct_search_calls_outside_service_provider():
    tree = _module("rag_api.py")

    direct_search_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "search"
    ]

    assert direct_search_calls == []


def test_generation_paths_use_tools_without_retrieval():
    tree = _module("rag_api.py")

    for function_name in ("rag_with_fc", "stream_rag"):
        function = _function(tree, function_name)
        calls = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "call_llm"
        ]
        assert calls
        for call in calls:
            tools_arg = next(kw.value for kw in call.keywords if kw.arg == "tools")
            assert isinstance(tools_arg, ast.Name)
            assert tools_arg.id == "GENERATION_TOOLS"


def test_rest_and_stream_share_delivery_metadata_builder():
    tree = _module("rag_api.py")

    assert _named_reference_count(_function(tree, "query"), "build_delivery_metadata") == 1
    assert _named_reference_count(_function(tree, "stream_rag"), "build_delivery_metadata") == 1
