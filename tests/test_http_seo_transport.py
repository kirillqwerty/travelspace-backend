import asyncio
from pathlib import Path

from server import HeadAsGetMiddleware


def test_head_requests_use_get_route_and_return_no_body():
    seen = {}
    messages = []

    async def inner(scope, receive, send):
        seen["method"] = scope["method"]
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-length", b"7")],
            }
        )
        await send({"type": "http.response.body", "body": b"content", "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def run():
        middleware = HeadAsGetMiddleware(inner)
        scope = {"type": "http", "method": "HEAD"}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())

    assert seen["method"] == "GET"
    assert messages[0]["status"] == 200
    assert messages[-1] == {
        "type": "http.response.body",
        "body": b"",
        "more_body": False,
    }
    assert all(message.get("body") != b"content" for message in messages)


def test_apache_config_redirects_http_and_caches_background_video():
    config = (Path(__file__).parents[1] / ".htaccess").read_text(encoding="utf-8")

    assert "RewriteCond %{HTTPS} !=on" in config
    assert "RewriteCond %{HTTP:X-Forwarded-Proto} !https [NC]" in config
    assert "ExpiresByType video/mp4 A2592000" in config
