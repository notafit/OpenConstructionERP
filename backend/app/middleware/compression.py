# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compress the responses that compress, and leave the rest alone.

Measured on the local stand: every screen loads a 2.44 MB application bundle and
a 2.21 MB locale chunk before it draws anything, and both went over the wire
uncompressed even though the browser asked for gzip on every request. The two
slow screens in the case audits, the snag register at 4.3 s and the bill editor
at 4.1 s, share that cost and differ only by their own chunk, which is 65 KB and
59 KB. The API was never the problem: the endpoints those screens call answer in
under a tenth of a second.

Starlette ships ``GZipMiddleware`` and it would do most of this, but it
compresses by content length alone. That means it also spends CPU on PDF
exports, GAEB archives and photo bytes, which are already compressed and come
out slightly larger, and it buffers streaming responses to do it. On a 3 GB server
that is the wrong trade, so this one asks what the body is before it spends
anything: text compresses, everything else is passed through untouched.

A response that already carries ``Content-Encoding`` is left as it is, so a
pre-compressed asset served straight from disk is never compressed twice.
"""

from __future__ import annotations

import gzip
import io
from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Content types worth the CPU. Everything else is either already compressed
#: (images, PDF, zip, fonts in woff2) or too small for the header to pay for.
COMPRESSIBLE_TYPES = (
    "text/",
    "application/json",
    "application/javascript",
    "application/xml",
    "application/manifest+json",
    "application/x-ndjson",
    "image/svg+xml",
)

#: Below this the gzip header and trailer eat the saving.
MINIMUM_SIZE = 1024


def _is_compressible(headers: Headers) -> bool:
    if headers.get("content-encoding"):
        return False
    content_type = headers.get("content-type", "").split(";")[0].strip().lower()
    return content_type.startswith(COMPRESSIBLE_TYPES)


def _accepts_gzip(headers: Headers) -> bool:
    return "gzip" in headers.get("accept-encoding", "").lower()


class CompressionMiddleware:
    """Gzip text responses whose size is known, pass everything else through.

    A response with no ``Content-Length`` is streaming, and buffering it to
    compress it would trade a transfer saving for unbounded memory, so those go
    through as they are.
    """

    def __init__(self, app: ASGIApp, minimum_size: int = MINIMUM_SIZE, compresslevel: int = 6) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _accepts_gzip(Headers(scope=scope)):
            await self.app(scope, receive, send)
            return
        await _GzipResponder(self.app, self.minimum_size, self.compresslevel)(scope, receive, send)


class _GzipResponder:
    """Decides on the response start message, then either compresses or forwards."""

    def __init__(self, app: ASGIApp, minimum_size: int, compresslevel: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel
        self.send: Send | None = None
        self.start_message: Message | None = None
        self.compressing = False
        self.body = bytearray()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.send = send
        await self.app(scope, receive, self._send)

    async def _send(self, message: Message) -> None:
        send: Callable[[Message], Awaitable[None]] = self.send  # type: ignore[assignment]

        if message["type"] == "http.response.start":
            headers = Headers(raw=message["headers"])
            try:
                declared = int(headers.get("content-length", ""))
            except ValueError:
                # No length means a streaming body, and buffering it to
                # compress it would trade transfer for unbounded memory.
                declared = -1
            self.compressing = _is_compressible(headers) and declared >= self.minimum_size
            self.start_message = message
            if not self.compressing:
                await send(message)
            return

        if message["type"] != "http.response.body" or not self.compressing:
            await send(message)
            return

        self.body.extend(message.get("body", b""))
        if message.get("more_body", False):
            return

        buffer = io.BytesIO()
        with gzip.GzipFile(mode="wb", fileobj=buffer, compresslevel=self.compresslevel, mtime=0) as archive:
            archive.write(bytes(self.body))
        packed = buffer.getvalue()

        start = self.start_message or {"type": "http.response.start", "status": 200, "headers": []}
        headers = MutableHeaders(raw=start["headers"])
        headers["Content-Encoding"] = "gzip"
        headers["Content-Length"] = str(len(packed))
        # Caches must not hand a gzipped body to a client that cannot read it.
        existing_vary = headers.get("Vary")
        if not existing_vary:
            headers["Vary"] = "Accept-Encoding"
        elif "accept-encoding" not in existing_vary.lower():
            headers["Vary"] = f"{existing_vary}, Accept-Encoding"

        await send(start)
        await send({"type": "http.response.body", "body": packed, "more_body": False})
