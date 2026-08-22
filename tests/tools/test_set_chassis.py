from unittest.mock import MagicMock

import pytest

from reachy_mini_conversation_app.tools.core_tools import ToolDependencies
from reachy_mini_conversation_app.tools.set_chassis import SetChassis


class _FakeChassisController:
    """Capture chassis API calls from the set_chassis tool."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self) -> dict[str, object]:
        self.calls.append(("status", None))
        return {"status": "ok", "response": {"running": True}}

    def tank(self, left: float, right: float, duration_s: float | None = None) -> dict[str, object]:
        self.calls.append(("tank", (left, right, duration_s)))
        return {"status": "ok", "response": {"ok": True}}

    def twist(self, velocity: float, turn: float, duration_s: float | None = None) -> dict[str, object]:
        self.calls.append(("twist", (velocity, turn, duration_s)))
        return {"status": "ok", "response": {"ok": True}}

    def stop(self) -> dict[str, object]:
        self.calls.append(("stop", None))
        return {"status": "ok", "response": {"ok": True}}

    def estop(self) -> dict[str, object]:
        self.calls.append(("estop", None))
        return {"status": "ok", "response": {"ok": True}}

    def clear(self) -> dict[str, object]:
        self.calls.append(("clear", None))
        return {"status": "ok", "response": {"ok": True}}


def test_set_chassis_requests_spoken_followup() -> None:
    """Chassis results should be summarized back to the user."""
    assert SetChassis.needs_response is True


def test_set_chassis_turn_schema_matches_firmware_mixing() -> None:
    """Positive twist turn values should be model-facing right turns."""
    description = SetChassis.parameters_schema["properties"]["turn"]["description"]

    assert "-1.0 left to 1.0 right" in description


@pytest.mark.asyncio
async def test_set_chassis_maps_status_stop_and_estop() -> None:
    """Direct chassis actions should call the matching controller methods."""
    chassis_controller = _FakeChassisController()
    deps = ToolDependencies(
        reachy_mini=MagicMock(),
        movement_manager=MagicMock(),
        chassis_controller=chassis_controller,
    )

    status = await SetChassis()(deps, action="status")
    stop = await SetChassis()(deps, action="stop")
    estop = await SetChassis()(deps, action="estop")
    clear = await SetChassis()(deps, action="clear")

    assert status["status"] == "ok"
    assert stop["status"] == "ok"
    assert estop["status"] == "ok"
    assert clear["status"] == "ok"
    assert chassis_controller.calls == [
        ("status", None),
        ("stop", None),
        ("estop", None),
        ("clear", None),
    ]


@pytest.mark.asyncio
async def test_set_chassis_maps_tank_and_clamps_values() -> None:
    """Tank drive should clamp normalized track values."""
    chassis_controller = _FakeChassisController()
    deps = ToolDependencies(
        reachy_mini=MagicMock(),
        movement_manager=MagicMock(),
        chassis_controller=chassis_controller,
    )

    result = await SetChassis()(deps, action="tank", left=1.4, right="-1.4")

    assert result["status"] == "ok"
    assert chassis_controller.calls == [("tank", (1.0, -1.0, None))]


@pytest.mark.asyncio
async def test_set_chassis_sends_firmware_timed_twist_then_stops() -> None:
    """Timed drive commands should send a firmware duration and finish with stop."""
    chassis_controller = _FakeChassisController()
    deps = ToolDependencies(
        reachy_mini=MagicMock(),
        movement_manager=MagicMock(),
        chassis_controller=chassis_controller,
    )

    result = await SetChassis()(deps, action="twist", velocity=0.2, turn=-0.1, duration_s=0.14)

    assert result["status"] == "ok"
    assert result["commands_sent"] == 1
    assert chassis_controller.calls[-1] == ("stop", None)
    assert chassis_controller.calls[0] == ("twist", (0.2, -0.1, 0.14))


@pytest.mark.asyncio
async def test_set_chassis_returns_error_when_unconfigured() -> None:
    """Missing optional hardware should be reported without raising."""
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())

    result = await SetChassis()(deps, action="status")

    assert result == {"error": "ESP32 chassis is not configured"}
