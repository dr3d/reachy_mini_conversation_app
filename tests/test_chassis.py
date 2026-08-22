import httpx

from reachy_mini_conversation_app.chassis import HttpChassisClient, HttpChassisSettings


def test_http_chassis_client_posts_tank_query() -> None:
    """Tank commands should post normalized track values to the chassis API."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "action": "tank"})

    client = HttpChassisClient(
        HttpChassisSettings(base_url="http://chassis.local"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.tank(0.2, -0.1)

    assert result["status"] == "ok"
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "http://chassis.local/api/tank?left=0.200&right=-0.100"


def test_http_chassis_client_posts_timed_twist_query() -> None:
    """Timed twist commands should pass a bounded firmware duration."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "action": "twist"})

    client = HttpChassisClient(
        HttpChassisSettings(base_url="http://chassis.local"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.twist(0.2, 0.1, duration_s=2.0)

    assert result["status"] == "ok"
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "http://chassis.local/api/twist?v=0.200&w=0.100&duration_ms=2000"


def test_http_chassis_client_posts_stop() -> None:
    """Stop commands should post to the chassis stop endpoint."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "action": "stop"})

    client = HttpChassisClient(
        HttpChassisSettings(base_url="http://chassis.local"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.stop()

    assert result["status"] == "ok"
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "http://chassis.local/api/stop"


def test_http_chassis_client_returns_structured_http_error() -> None:
    """HTTP failures should be returned as tool-safe errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "nope"})

    client = HttpChassisClient(
        HttpChassisSettings(base_url="http://chassis.local"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.get_status()

    assert "error" in result
    assert result["url"] == "http://chassis.local/api/status"
