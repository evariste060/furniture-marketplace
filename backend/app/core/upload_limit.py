"""Reject oversized image uploads while the request body is still being received (module 7).

FastAPI parses a multipart body completely before any endpoint or dependency runs, so a size
check inside the endpoint would only happen after the whole upload was read. This ASGI
middleware sits in front of the upload route instead. It refuses a declared Content-Length over
the limit, and also counts the bytes that actually arrive, so a missing or false Content-Length
cannot get around it. At most `max_body` bytes are ever held in memory.

Before answering 413 it reads and discards the rest of the body (up to DRAIN_LIMIT_BYTES), so the
client actually receives the response: closing the connection mid-upload makes many clients see a
connection reset instead. A body beyond DRAIN_LIMIT_BYTES gets the 413 and a closed connection.

The limit covers the whole request: the file (5 MB for images, 10 MB for catalogue imports) plus
room for the multipart framing and small form fields. Each endpoint then checks the file itself
against its exact limit. One middleware instance is added per limited route.
"""

import json
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

# Room for the multipart framing and the small form fields (variant_id, alt_text) on top of the
# 5 MB file itself.
UPLOAD_FORM_OVERHEAD_BYTES = 64 * 1024
# Discarded, never stored: how much of an oversized body is read so the 413 can be delivered.
DRAIN_LIMIT_BYTES = 32 * 1024 * 1024

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

IMAGE_TOO_LARGE_MESSAGE = "The upload is larger than 5 MB."


def too_large_body(message: str) -> bytes:
    return json.dumps(
        {"error": {"code": "file_too_large", "message": message, "details": None}}
    ).encode()


TOO_LARGE_BODY = too_large_body(IMAGE_TOO_LARGE_MESSAGE)


class UploadSizeLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        path_pattern: str,
        max_body: int,
        message: str = IMAGE_TOO_LARGE_MESSAGE,
    ) -> None:
        self.app = app
        self.path = re.compile(path_pattern)
        self.max_body = max_body
        self.body = too_large_body(message)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not self.path.fullmatch(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return

        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_body:
            if int(declared) > DRAIN_LIMIT_BYTES:
                await self._too_large(send, self.body, close=True)
                return
            await self._too_large(send, self.body, close=not await self._drain(receive, 0))
            return

        chunks: list[bytes] = []
        received = 0
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            received += len(chunk)
            more = message.get("more_body", False)
            if received > self.max_body:
                chunks.clear()  # never hold an oversized body
                drained = not more or await self._drain(receive, received)
                await self._too_large(send, self.body, close=not drained)
                return
            chunks.append(chunk)

        body = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()  # later messages, such as a disconnect

        await self.app(scope, replay, send)

    @staticmethod
    async def _drain(receive: Receive, already: int) -> bool:
        """Read and discard the rest of the body. False if it ran past DRAIN_LIMIT_BYTES or the
        client disconnected, in which case the connection is closed after the 413."""
        total = already
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return False
            total += len(message.get("body", b""))
            if total > DRAIN_LIMIT_BYTES:
                return False
            if not message.get("more_body", False):
                return True

    @staticmethod
    async def _too_large(send: Send, body: bytes, *, close: bool = False) -> None:
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if close:
            headers.append((b"connection", b"close"))
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": body})
