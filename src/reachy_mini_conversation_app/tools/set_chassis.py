import asyncio
import logging
from typing import Any
from collections.abc import Callable

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

CHASSIS_ACTIONS: tuple[str, ...] = ("status", "stop", "estop", "clear", "tank", "twist")
MAX_DURATION_S = 5.0


def _clamp_float(value: object, low: float, high: float) -> float:
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"Expected a number, got {type(value).__name__}")
    number = float(value)
    return min(max(number, low), high)


class SetChassis(Tool):
    """Control the optional ESP32 tracked chassis."""

    name = "set_chassis"
    description = "Control the optional ESP32 tracked chassis with stop, e-stop, tank drive, twist drive, or status."
    needs_response = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(CHASSIS_ACTIONS),
                "description": "Chassis action. Use stop before/after movement, estop for urgent safety, clear to clear e-stop.",
            },
            "left": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
                "description": "Left track speed for tank action, -1.0 reverse to 1.0 forward.",
            },
            "right": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
                "description": "Right track speed for tank action, -1.0 reverse to 1.0 forward.",
            },
            "velocity": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
                "description": "Forward/reverse velocity for twist action, -1.0 reverse to 1.0 forward.",
            },
            "turn": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
                "description": "Turn rate for twist action, -1.0 left to 1.0 right in firmware mixing.",
            },
            "duration_s": {
                "type": "number",
                "minimum": 0.0,
                "maximum": MAX_DURATION_S,
                "description": "Optional movement duration for a firmware-timed command, capped at 5 seconds. Omit or use 0 for one command.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        """Control the optional ESP32 tracked chassis."""
        chassis_controller = deps.chassis_controller
        if chassis_controller is None:
            return {"error": "ESP32 chassis is not configured"}

        logger.info("Tool call: set_chassis args=%s", kwargs)
        action = str(kwargs.get("action") or "").strip().lower()

        try:
            if action == "status":
                return await asyncio.to_thread(chassis_controller.get_status)
            if action == "stop":
                return await asyncio.to_thread(chassis_controller.stop)
            if action == "estop":
                return await asyncio.to_thread(chassis_controller.estop)
            if action == "clear":
                return await asyncio.to_thread(chassis_controller.clear)
            if action == "tank":
                left = _clamp_float(kwargs.get("left"), -1.0, 1.0)
                right = _clamp_float(kwargs.get("right"), -1.0, 1.0)
                return await self._run_drive(
                    chassis_controller.stop,
                    lambda duration_s: chassis_controller.tank(left, right, duration_s),
                    kwargs,
                )
            if action == "twist":
                velocity = _clamp_float(kwargs.get("velocity"), -1.0, 1.0)
                turn = _clamp_float(kwargs.get("turn"), -1.0, 1.0)
                return await self._run_drive(
                    chassis_controller.stop,
                    lambda duration_s: chassis_controller.twist(velocity, turn, duration_s),
                    kwargs,
                )
        except ValueError as exc:
            return {"error": str(exc)}

        return {"error": f"Unknown chassis action: {action}"}

    async def _run_drive(
        self,
        stop: Callable[[], dict[str, object]],
        call_once: Callable[[float | None], dict[str, object]],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        duration_s = _clamp_float(kwargs.get("duration_s", 0.0), 0.0, MAX_DURATION_S)
        if duration_s <= 0.0:
            return await asyncio.to_thread(call_once, None)

        drive_result = await asyncio.to_thread(call_once, duration_s)
        await asyncio.sleep(duration_s)
        stop_result = await asyncio.to_thread(stop)
        errors = [result["error"] for result in [drive_result, stop_result] if "error" in result]
        if errors:
            return {"error": "; ".join(str(error) for error in errors), "drive": drive_result, "stop": stop_result}
        return {
            "status": "ok",
            "duration_s": duration_s,
            "commands_sent": 1,
            "drive": drive_result,
            "stop": stop_result,
        }
