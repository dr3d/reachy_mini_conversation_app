from unittest.mock import MagicMock

import pytest

from reachy_mini_conversation_app.tools.set_eyes import SetEyes
from reachy_mini_conversation_app.tools.core_tools import ToolDependencies


class _FakeEyesController:
    """Capture eye API calls from the set_eyes tool."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_state(self) -> dict[str, object]:
        self.calls.append(("state", None))
        return {"status": "ok", "response": {"running": True}}

    def control(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("control", payload))
        return {"status": "ok", "response": {"ok": True}}

    def emotion(self, name: str, duration_s: float | None = None) -> dict[str, object]:
        self.calls.append(("emotion", (name, duration_s)))
        return {"status": "ok", "response": {"ok": True}}

    def expression(self, name: str, duration_s: float) -> dict[str, object]:
        self.calls.append(("expression", (name, duration_s)))
        return {"status": "ok", "response": {"ok": True}}

    def beat(self, name: str) -> dict[str, object]:
        self.calls.append(("beat", name))
        return {"status": "ok", "response": {"ok": True}}

    def style(self, name: str) -> dict[str, object]:
        self.calls.append(("style", name))
        return {"status": "ok", "response": {"ok": True}}

    def blink(self, eye: str = "both") -> dict[str, object]:
        self.calls.append(("blink", eye))
        return {"status": "ok", "response": {"ok": True}}

    def wink(self, eye: str) -> dict[str, object]:
        self.calls.append(("wink", eye))
        return {"status": "ok", "response": {"ok": True}}

    def sleep(self, duration_s: float) -> dict[str, object]:
        self.calls.append(("sleep", duration_s))
        return {"status": "ok", "response": {"ok": True}}

    def release(self) -> dict[str, object]:
        self.calls.append(("release", None))
        return {"status": "ok", "response": {"ok": True}}

    def cue(self, action: str, payload: dict[str, object] | None = None) -> None:
        self.calls.append(("cue", (action, payload)))

    def close(self) -> None:
        self.calls.append(("close", None))


@pytest.mark.asyncio
async def test_set_eyes_maps_expression_gaze_and_blink() -> None:
    """The tool should translate high-level inputs to HTTP API operations."""
    eyes_controller = _FakeEyesController()
    deps = ToolDependencies(
        reachy_mini=MagicMock(),
        movement_manager=MagicMock(),
        eyes_controller=eyes_controller,
    )

    result = await SetEyes()(
        deps,
        action="blink",
        expression="surprised",
        beat="thoughtful",
        style="robot",
        duration_s=0.7,
        gaze={"x": 0.5, "y": -0.25, "z": 420},
        brightness=0.6,
        move_ms=180,
        mouth_shape="sinister",
        mouth_talking=True,
        mouth_energy=0.8,
    )

    assert result["status"] == "ok"
    assert eyes_controller.calls == [
        ("blink", "both"),
        ("expression", ("surprised", 0.7)),
        ("beat", "thoughtful"),
        ("style", "robot"),
        (
            "control",
            {
                "brightness": 0.6,
                "mouth": {"shape": "sneer", "duration": 0.7, "talking": True, "energy": 0.8},
                "gaze": {"x": 0.5, "y": -0.25, "duration": 0.7, "z": 420.0, "move_ms": 180},
            },
        ),
    ]


@pytest.mark.asyncio
async def test_set_eyes_maps_style_aliases() -> None:
    """Style aliases should route to renderer style control."""
    eyes_controller = _FakeEyesController()
    deps = ToolDependencies(
        reachy_mini=MagicMock(),
        movement_manager=MagicMock(),
        eyes_controller=eyes_controller,
    )

    result = await SetEyes()(deps, action="dot_style", style="slits", expression="Frighten")

    assert result["status"] == "ok"
    assert eyes_controller.calls == [
        ("style", "robot"),
        ("expression", ("afraid", 3.0)),
        ("style", "sinister"),
    ]


@pytest.mark.asyncio
async def test_set_eyes_maps_emotion_alias_duration() -> None:
    """Emotion aliases should be normalized before calling the eye API."""
    eyes_controller = _FakeEyesController()
    deps = ToolDependencies(
        reachy_mini=MagicMock(),
        movement_manager=MagicMock(),
        eyes_controller=eyes_controller,
    )

    result = await SetEyes()(deps, emotion="Frightened")

    assert result["status"] == "ok"
    assert eyes_controller.calls == [("emotion", ("afraid", 6.0))]


@pytest.mark.asyncio
async def test_set_eyes_returns_error_when_unconfigured() -> None:
    """Missing optional hardware should be reported without raising."""
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())

    result = await SetEyes()(deps, emotion="happy")

    assert result == {"error": "ESP32 eyes are not configured"}
