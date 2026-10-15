"""Pure-ASGI middleware: security headers and request-body size limits."""

from __future__ import annotations

import json

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' blob: data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "manifest-src 'self'; "
    "worker-src 'self'; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app, *, hsts: bool):
        self.app = app
        self.headers = [
            (b"content-security-policy", CSP.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"cross-origin-opener-policy", b"same-origin"),
            (b"cross-origin-resource-policy", b"same-origin"),
            (b"permissions-policy", b"camera=(self), microphone=(), geolocation=(), payment=(), usb=()"),
        ]
        if hsts:
            self.headers.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_api = scope["path"].startswith("/api/")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0] != b"server"]
                headers.extend(self.headers)
                if is_api:
                    # Patient data must never sit in browser or proxy caches.
                    headers = [h for h in headers if h[0] != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                    headers.append((b"pragma", b"no-cache"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Reject oversized bodies early - FastAPI/Starlette impose no limit themselves."""

    def __init__(self, app, *, default_limit: int, bulk_limit: int, bulk_prefixes: tuple[str, ...]):
        self.app = app
        self.default_limit = default_limit
        self.bulk_limit = bulk_limit
        self.bulk_prefixes = bulk_prefixes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.bulk_limit if scope["path"].startswith(self.bulk_prefixes) else self.default_limit
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > limit:
                        return await _reject(send, limit)
                except ValueError:
                    return await _reject(send, limit)

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _reject(send, limit)


class _BodyTooLarge(Exception):
    pass


async def _reject(send, limit: int) -> None:
    body = json.dumps(
        {"detail": f"حجم الطلب أكبر من المسموح ({limit // (1024 * 1024)} ميجابايت)"}, ensure_ascii=False
    ).encode()
    try:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": body})
    except RuntimeError:  # pragma: no cover - response already started
        pass
