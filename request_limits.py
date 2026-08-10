"""ASGI request-body limit applied before FastAPI materializes JSON payloads."""

from __future__ import annotations

import json

MAX_REQUEST_BODY_BYTES = 14 * 1024 * 1024


class RequestBodyLimitMiddleware:
    def __init__(self, app, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, send) -> None:
        body = json.dumps({"error": "Request body too large"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > self.max_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                pass

        consumed = 0
        oversized = False

        async def limited_receive():
            nonlocal consumed, oversized
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    oversized = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def limited_send(message):
            if not oversized:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except Exception:
            if not oversized:
                raise
        if oversized:
            await self._reject(send)
