import logging
import threading
from typing import Protocol
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 0.8


def _optional_float(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float, str)):
        return float(value)
    return default


class EyesController(Protocol):
    """Controls optional expressive eye hardware."""

    def get_state(self) -> dict[str, object]:
        """Return the current eye API state."""
        ...

    def control(self, payload: dict[str, object]) -> dict[str, object]:
        """Apply a generic eye control payload."""
        ...

    def emotion(self, name: str, duration_s: float | None = None) -> dict[str, object]:
        """Apply an eye emotion preset."""
        ...

    def expression(self, name: str, duration_s: float) -> dict[str, object]:
        """Trigger a short eye expression."""
        ...

    def beat(self, name: str) -> dict[str, object]:
        """Start one scripted idle beat."""
        ...

    def style(self, name: str) -> dict[str, object]:
        """Apply an eye renderer style."""
        ...

    def blink(self, eye: str = "both") -> dict[str, object]:
        """Trigger an eye blink."""
        ...

    def wink(self, eye: str) -> dict[str, object]:
        """Trigger one eye wink."""
        ...

    def sleep(self, duration_s: float) -> dict[str, object]:
        """Blank the eyes for a duration."""
        ...

    def release(self) -> dict[str, object]:
        """Return the eyes to autonomous behavior."""
        ...

    def cue(self, action: str, payload: dict[str, object] | None = None) -> None:
        """Send an eye cue in the background."""
        ...

    def close(self) -> None:
        """Close the hardware connection."""
        ...


@dataclass(frozen=True)
class HttpEyesSettings:
    """HTTP settings for an ESP32 or RP5 eye-control API."""

    base_url: str
    timeout_s: float = DEFAULT_TIMEOUT_S


class HttpEyesClient:
    """HTTP client for the Reachy eyes control API."""

    def __init__(self, settings: HttpEyesSettings, http_client: httpx.Client | None = None) -> None:
        """Create a reusable HTTP client for the configured eye API."""
        self._settings = settings
        self._base_url = settings.base_url.rstrip("/") + "/"
        self._client = http_client or httpx.Client(timeout=settings.timeout_s)
        self._lock = threading.Lock()

    def get_state(self) -> dict[str, object]:
        """Return the current eye API state."""
        return self._request("GET", "state")

    def control(self, payload: dict[str, object]) -> dict[str, object]:
        """Apply a generic eye control payload."""
        return self._request("POST", "control", payload)

    def emotion(self, name: str, duration_s: float | None = None) -> dict[str, object]:
        """Apply an eye emotion preset."""
        payload: dict[str, object] = {"name": name}
        if duration_s is not None:
            payload["duration"] = duration_s
        return self._request("POST", "emotion", payload)

    def expression(self, name: str, duration_s: float) -> dict[str, object]:
        """Trigger a short eye expression."""
        return self._request("POST", "expression", {"name": name, "duration": duration_s})

    def beat(self, name: str) -> dict[str, object]:
        """Start one scripted idle beat."""
        return self._request("POST", "beat", {"name": name})

    def style(self, name: str) -> dict[str, object]:
        """Apply an eye renderer style."""
        return self._request("POST", "style", {"name": name})

    def blink(self, eye: str = "both") -> dict[str, object]:
        """Trigger an eye blink."""
        return self._request("POST", "blink", {"eye": eye})

    def wink(self, eye: str) -> dict[str, object]:
        """Trigger one eye wink."""
        return self._request("POST", "wink", {"eye": eye})

    def sleep(self, duration_s: float) -> dict[str, object]:
        """Blank the eyes for a duration."""
        return self._request("POST", "sleep", {"duration": duration_s})

    def release(self) -> dict[str, object]:
        """Return the eyes to autonomous behavior."""
        return self._request("POST", "release")

    def cue(self, action: str, payload: dict[str, object] | None = None) -> None:
        """Run one non-critical eye cue in a daemon thread."""

        def send_cue() -> None:
            if action == "control":
                result = self.control(payload or {})
            elif action == "emotion":
                cue_payload = payload or {}
                duration = cue_payload.get("duration")
                result = self.emotion(
                    str(cue_payload.get("name", "neutral")),
                    _optional_float(duration, 0.5) if duration is not None else None,
                )
            elif action == "expression":
                cue_payload = payload or {}
                result = self.expression(
                    str(cue_payload.get("name", "surprised")),
                    _optional_float(cue_payload.get("duration"), 0.5),
                )
            elif action == "beat":
                result = self.beat(str((payload or {}).get("name", "thoughtful")))
            elif action == "style":
                result = self.style(str((payload or {}).get("name", "friendly")))
            elif action == "blink":
                result = self.blink(str((payload or {}).get("eye", "both")))
            elif action == "wink":
                result = self.wink(str((payload or {}).get("eye", "left")))
            elif action == "sleep":
                result = self.sleep(_optional_float((payload or {}).get("duration"), 0.0))
            elif action == "release":
                result = self.release()
            elif action == "state":
                result = self.get_state()
            else:
                logger.debug("Ignoring unknown ESP32 eyes cue action: %s", action)
                return
            if "error" in result:
                logger.debug("ESP32 eyes cue skipped: %s", result["error"])

        threading.Thread(target=send_cue, daemon=True, name="esp32-eyes-http-cue").start()

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        url = urljoin(self._base_url, path)
        try:
            with self._lock:
                response = self._client.request(method, url, json=payload)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("ESP32 eyes HTTP request failed: %s %s: %s", method, url, exc)
            return {"error": f"ESP32 eyes request failed: {type(exc).__name__}: {exc}", "url": url}

        if isinstance(data, dict):
            if data.get("ok") is False:
                error = data.get("error", "ESP32 eyes API returned ok=false")
                return {"error": str(error), "url": url, "response": data}
            return {"status": "ok", "url": url, "response": data}
        return {"error": "ESP32 eyes API returned a non-object response", "url": url, "response": data}
