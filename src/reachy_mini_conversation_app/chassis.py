import logging
import threading
from typing import Protocol
from dataclasses import dataclass
from urllib.parse import urljoin, urlencode

import httpx


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 0.8


class ChassisController(Protocol):
    """Controls optional tracked chassis hardware."""

    def get_status(self) -> dict[str, object]:
        """Return the current chassis API status."""
        ...

    def tank(self, left: float, right: float, duration_s: float | None = None) -> dict[str, object]:
        """Set tank-drive targets."""
        ...

    def twist(self, velocity: float, turn: float, duration_s: float | None = None) -> dict[str, object]:
        """Set velocity/turn drive targets."""
        ...

    def stop(self) -> dict[str, object]:
        """Stop both tracks."""
        ...

    def estop(self) -> dict[str, object]:
        """Latch the chassis e-stop."""
        ...

    def clear(self) -> dict[str, object]:
        """Clear the chassis e-stop."""
        ...

    def close(self) -> None:
        """Close the hardware connection."""
        ...


@dataclass(frozen=True)
class HttpChassisSettings:
    """HTTP settings for an ESP32 chassis-control API."""

    base_url: str
    timeout_s: float = DEFAULT_TIMEOUT_S


class HttpChassisClient:
    """HTTP client for the Reachy Mini chassis control API."""

    def __init__(self, settings: HttpChassisSettings, http_client: httpx.Client | None = None) -> None:
        """Create a reusable HTTP client for the configured chassis API."""
        self._settings = settings
        self._base_url = settings.base_url.rstrip("/") + "/"
        self._client = http_client or httpx.Client(timeout=settings.timeout_s)
        self._lock = threading.Lock()

    def get_status(self) -> dict[str, object]:
        """Return the current chassis API status."""
        return self._request("GET", "api/status")

    def tank(self, left: float, right: float, duration_s: float | None = None) -> dict[str, object]:
        """Set tank-drive targets."""
        query = urlencode(self._drive_query({"left": f"{left:.3f}", "right": f"{right:.3f}"}, duration_s))
        return self._request("POST", f"api/tank?{query}")

    def twist(self, velocity: float, turn: float, duration_s: float | None = None) -> dict[str, object]:
        """Set velocity/turn drive targets."""
        query = urlencode(self._drive_query({"v": f"{velocity:.3f}", "w": f"{turn:.3f}"}, duration_s))
        return self._request("POST", f"api/twist?{query}")

    def stop(self) -> dict[str, object]:
        """Stop both tracks."""
        return self._request("POST", "api/stop")

    def estop(self) -> dict[str, object]:
        """Latch the chassis e-stop."""
        return self._request("POST", "api/estop")

    def clear(self) -> dict[str, object]:
        """Clear the chassis e-stop."""
        return self._request("POST", "api/clear")

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def _drive_query(self, query: dict[str, str], duration_s: float | None) -> dict[str, str]:
        if duration_s is not None and duration_s > 0.0:
            query["duration_ms"] = str(round(duration_s * 1000))
        return query

    def _request(self, method: str, path: str) -> dict[str, object]:
        url = urljoin(self._base_url, path)
        try:
            with self._lock:
                response = self._client.request(method, url)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("ESP32 chassis HTTP request failed: %s %s: %s", method, url, exc)
            return {"error": f"ESP32 chassis request failed: {type(exc).__name__}: {exc}", "url": url}

        if isinstance(data, dict):
            if data.get("ok") is False:
                error = data.get("error", "ESP32 chassis API returned ok=false")
                return {"error": str(error), "url": url, "response": data}
            return {"status": "ok", "url": url, "response": data}
        return {"error": "ESP32 chassis API returned a non-object response", "url": url, "response": data}
