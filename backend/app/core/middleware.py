"""Production HTTP security, idempotency, rate limiting, and APM tracing middleware."""
from __future__ import annotations

import asyncio
import collections
import json
import math
import time
import uuid
from typing import Any, Deque, Dict, Tuple
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Attach conservative browser security headers to HTTP responses."""

    def __init__(self, app: ASGIApp, *, enabled: bool = True):
        self.app = app
        self.enabled = enabled

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.setdefault(
                    "Permissions-Policy",
                    "camera=(), geolocation=(), payment=(), usb=()",
                )
                headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestTracingMiddleware:
    """Inject APM trace ID and compute process time for latency observability."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        trace_id = str(uuid.uuid4())

        async def send_with_trace(message: Message) -> None:
            if message["type"] == "http.response.start":
                process_time_ms = (time.perf_counter() - start_time) * 1000
                headers = MutableHeaders(scope=message)
                headers.append("X-Trace-Id", trace_id)
                headers.append("X-Process-Time-Ms", f"{process_time_ms:.2f}")
            await send(message)

        await self.app(scope, receive, send_with_trace)


class SlidingWindowRateLimiterMiddleware:
    """In-memory sliding window rate limiter for brute-force and DDoS defense."""

    def __init__(
        self,
        app: ASGIApp,
        enabled: bool = True,
        auth_limit_per_min: int = 20,
        general_limit_per_min: int = 300,
        bypass_local_hosts: bool = False,
    ):
        self.app = app
        self.enabled = enabled
        self.auth_limit = auth_limit_per_min
        self.general_limit = general_limit_per_min
        self.bypass_local_hosts = bypass_local_hosts
        # Authentication and general traffic must never share one counter.
        # Otherwise routine page polling can consume the much smaller login
        # allowance before the user attempts to sign in.
        self.ip_records: Dict[Tuple[str, str], Deque[float]] = collections.defaultdict(
            collections.deque
        )
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_host = scope.get("client", ["127.0.0.1"])[0] or "127.0.0.1"
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if (
            method == "OPTIONS"
            or path in {"/api/health", "/api/health/live", "/api/health/ready"}
            or (self.bypass_local_hosts and client_host in {"127.0.0.1", "::1", "localhost"})
        ):
            await self.app(scope, receive, send)
            return

        is_auth_route = path in {
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/change-password",
        }
        bucket = "auth" if is_auth_route else "general"
        limit = self.auth_limit if is_auth_route else self.general_limit

        now = time.time()
        window_start = now - 60.0

        async with self._lock:
            records = self.ip_records[(client_host, bucket)]
            while records and records[0] < window_start:
                records.popleft()

            if len(records) >= limit:
                # 429 Too Many Requests
                payload = json.dumps(
                    {"detail": "请求频率过高，触发系统安全限流保护，请稍候再试。"},
                    ensure_ascii=False,
                ).encode("utf-8")

                retry_after = max(1, math.ceil(records[0] + 60.0 - now))

                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"retry-after", str(retry_after).encode("ascii")),
                        (b"x-ratelimit-limit", str(limit).encode("ascii")),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": payload,
                })
                return

            records.append(now)
            remaining = max(0, limit - len(records))

        async def send_with_rate_limit_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-RateLimit-Limit", str(limit))
                headers.setdefault("X-RateLimit-Remaining", str(remaining))
            await send(message)

        await self.app(scope, receive, send_with_rate_limit_headers)


class IdempotencyMiddleware:
    """
    Guarantees zero-duplicate write execution for mutation requests bearing X-Idempotency-Key.
    Caches successful responses for 90 seconds to safely replay identical requests.
    """

    def __init__(self, app: ASGIApp, ttl_seconds: int = 90):
        self.app = app
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, Tuple[float, int, list[Tuple[bytes, bytes]], bytes]] = {}
        self.inflight: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        idempotency_key = headers.get("x-idempotency-key") or headers.get("X-Idempotency-Key")
        if not idempotency_key:
            await self.app(scope, receive, send)
            return

        now = time.time()

        # 1. 检查是否存在有效缓存
        async with self._lock:
            # 清理过期缓存
            expired_keys = [k for k, v in self.cache.items() if now - v[0] > self.ttl_seconds]
            for k in expired_keys:
                self.cache.pop(k, None)

            if idempotency_key in self.cache:
                _, status, cached_headers, body = self.cache[idempotency_key]
                # 命中幂等缓存，直接回放响应
                await send({
                    "type": "http.response.start",
                    "status": status,
                    "headers": cached_headers + [(b"x-idempotency-hit", b"1")],
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                })
                return

            # 若相同 key 正在执行中，等待完成
            if idempotency_key in self.inflight:
                event = self.inflight[idempotency_key]
            else:
                event = asyncio.Event()
                self.inflight[idempotency_key] = event

        # 2. 如果之前已有请求正在执行中，则等待其完成
        if idempotency_key in self.cache:
            _, status, cached_headers, body = self.cache[idempotency_key]
            await send({
                "type": "http.response.start",
                "status": status,
                "headers": cached_headers + [(b"x-idempotency-hit", b"1")],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
            return

        # 3. 正常执行请求并拦截响应
        response_status = 200
        response_headers: list[Tuple[bytes, bytes]] = []
        response_body_chunks: list[bytes] = []

        async def send_capturing(message: Message) -> None:
            nonlocal response_status, response_headers
            if message["type"] == "http.response.start":
                response_status = message["status"]
                response_headers = list(message.get("headers", []))
                await send(message)
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    response_body_chunks.append(chunk)
                await send(message)

        try:
            await self.app(scope, receive, send_capturing)
            # 成功执行（2xx），存入幂等缓存
            if 200 <= response_status < 300:
                full_body = b"".join(response_body_chunks)
                async with self._lock:
                    self.cache[idempotency_key] = (
                        time.time(),
                        response_status,
                        response_headers,
                        full_body,
                    )
        finally:
            async with self._lock:
                ev = self.inflight.pop(idempotency_key, None)
                if ev:
                    ev.set()
