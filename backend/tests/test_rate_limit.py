import unittest

from app.core.middleware import SlidingWindowRateLimiterMiddleware


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _request(middleware, path: str, host: str = "198.51.100.10"):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "client": (host, 12345),
            "headers": [],
        },
        receive,
        send,
    )
    return next(item for item in messages if item["type"] == "http.response.start")


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_and_general_requests_use_independent_buckets(self):
        limiter = SlidingWindowRateLimiterMiddleware(
            _ok_app, auth_limit_per_min=1, general_limit_per_min=2
        )
        self.assertEqual((await _request(limiter, "/api/users/me"))["status"], 204)
        self.assertEqual((await _request(limiter, "/api/users/me"))["status"], 204)
        self.assertEqual((await _request(limiter, "/api/users/me"))["status"], 429)
        self.assertEqual((await _request(limiter, "/api/auth/login"))["status"], 204)
        self.assertEqual((await _request(limiter, "/api/auth/login"))["status"], 429)

    async def test_local_debug_bypass_only_applies_to_loopback(self):
        limiter = SlidingWindowRateLimiterMiddleware(
            _ok_app,
            auth_limit_per_min=1,
            general_limit_per_min=1,
            bypass_local_hosts=True,
        )
        for _ in range(4):
            self.assertEqual(
                (await _request(limiter, "/api/users/me", "127.0.0.1"))["status"],
                204,
            )
        self.assertEqual(
            (await _request(limiter, "/api/users/me", "203.0.113.8"))["status"], 204
        )
        self.assertEqual(
            (await _request(limiter, "/api/users/me", "203.0.113.8"))["status"], 429
        )

    async def test_health_checks_do_not_consume_general_allowance(self):
        limiter = SlidingWindowRateLimiterMiddleware(
            _ok_app, auth_limit_per_min=1, general_limit_per_min=1
        )
        for _ in range(3):
            self.assertEqual((await _request(limiter, "/api/health/ready"))["status"], 204)
        self.assertEqual((await _request(limiter, "/api/users/me"))["status"], 204)
        limited = await _request(limiter, "/api/users/me")
        self.assertEqual(limited["status"], 429)
        headers = dict(limited["headers"])
        self.assertGreaterEqual(int(headers[b"retry-after"]), 1)
        self.assertEqual(headers[b"x-ratelimit-remaining"], b"0")


if __name__ == "__main__":
    unittest.main()
