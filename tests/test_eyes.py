import json

import httpx

from reachy_mini_conversation_app.eyes import HttpEyesClient, HttpEyesSettings


def test_http_eyes_client_posts_emotion_payload() -> None:
    """Emotion cues should post to the eye API."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client = HttpEyesClient(
        HttpEyesSettings(base_url="http://eyes.local"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.emotion("happy")

    assert result["status"] == "ok"
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "http://eyes.local/emotion"
    assert json.loads(requests[0].content) == {"name": "happy"}


def test_http_eyes_client_posts_style_payload() -> None:
    """Renderer style cues should post to the eye API."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client = HttpEyesClient(
        HttpEyesSettings(base_url="http://eyes.local"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.style("robot")

    assert result["status"] == "ok"
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "http://eyes.local/style"
    assert json.loads(requests[0].content) == {"name": "robot"}


def test_http_eyes_client_returns_structured_http_error() -> None:
    """HTTP failures should be returned as tool-safe errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "nope"})

    client = HttpEyesClient(
        HttpEyesSettings(base_url="http://eyes.local"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.blink()

    assert "error" in result
    assert result["url"] == "http://eyes.local/blink"
