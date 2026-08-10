import asyncio
import json

from request_limits import RequestBodyLimitMiddleware


def run_asgi_request(chunks: list[bytes], *, content_length: int | None, limit: int):
    app_called = False
    sent = []

    async def app(scope, receive, send):
        nonlocal app_called
        app_called = True
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("ascii")))
    scope = {"type": "http", "method": "POST", "path": "/doc/import", "headers": headers}
    queue = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]

    async def receive():
        return queue.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(RequestBodyLimitMiddleware(app, max_bytes=limit)(scope, receive, send))
    return app_called, sent


def test_content_length_over_limit_is_rejected_before_downstream_app() -> None:
    app_called, sent = run_asgi_request([b"ignored"], content_length=11, limit=10)

    assert app_called is False
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"]) == {"error": "Request body too large"}


def test_chunked_body_over_limit_suppresses_downstream_response_and_returns_413() -> None:
    app_called, sent = run_asgi_request([b"123456", b"78901"], content_length=None, limit=10)

    assert app_called is True
    assert [message["type"] for message in sent] == [
        "http.response.start",
        "http.response.body",
    ]
    assert sent[0]["status"] == 413


def test_body_at_limit_reaches_downstream_app() -> None:
    app_called, sent = run_asgi_request([b"12345", b"67890"], content_length=10, limit=10)

    assert app_called is True
    assert sent[0]["status"] == 204
