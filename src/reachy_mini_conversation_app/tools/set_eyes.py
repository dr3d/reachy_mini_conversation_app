import asyncio
import logging
from typing import Any

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

DEFAULT_EMOTION_DURATION_S = 6.0
DEFAULT_EXPRESSION_DURATION_S = 3.0
DEFAULT_GAZE_DURATION_S = 5.0
DEFAULT_MOUTH_DURATION_S = 2.5

EYE_EMOTIONS: tuple[str, ...] = (
    "random",
    "neutral",
    "calm",
    "happy",
    "curious",
    "surprised",
    "suspicious",
    "afraid",
    "fear",
    "frighten",
    "frightened",
    "scared",
    "angry",
    "sleepy",
    "sleep",
    "goofy",
    "robotic",
    "wonder",
    "glitchy",
    "delighted",
    "bashful",
    "bored",
    "focused",
    "confused",
    "proud",
    "mischief",
    "affection",
)
EYE_EXPRESSIONS: tuple[str, ...] = (
    "calm",
    "curious",
    "surprised",
    "suspicious",
    "afraid",
    "fear",
    "frighten",
    "frightened",
    "scared",
    "angry",
    "sleepy",
    "goofy",
    "robotic",
    "wonder",
    "glitchy",
    "happy",
    "delighted",
    "bashful",
    "bored",
    "focused",
    "confused",
    "proud",
    "mischief",
    "affection",
)
EYE_BEATS: tuple[str, ...] = (
    "slow_smile",
    "affection",
    "inspect",
    "thoughtful",
    "daydream",
    "mischief",
    "confused",
    "focus_lock",
    "double_take",
    "goofy",
    "drowsy",
    "robot_scan",
    "wary",
    "startle",
)
EYE_STYLES: tuple[str, ...] = (
    "friendly",
    "classic",
    "cartoony",
    "cartoon",
    "robot",
    "row_body",
    "dot",
    "big_dot",
    "sinister",
    "slit",
    "slits",
    "cat_eye",
    "red",
    "sleepy",
    "steel",
)
EYE_ACTIONS: tuple[str, ...] = (
    "release",
    "sleep",
    "wake",
    "blink",
    "double_blink",
    "left_wink",
    "right_wink",
    "status",
    "friendly_style",
    "classic_style",
    "cartoony_style",
    "robot_style",
    "dot_style",
    "sinister_style",
    "sleepy_style",
)
MOUTH_SHAPES: tuple[str, ...] = (
    "neutral",
    "smile",
    "smirk",
    "smirk_left",
    "smirk_right",
    "open",
    "wide",
    "frown",
    "grimace",
    "teeth",
    "sneer",
    "sinister",
    "sleep",
)
MOUTH_STYLES: tuple[str, ...] = (
    "human",
    "humanistic",
    "robot",
)

STYLE_ACTIONS: dict[str, str] = {
    "friendly_style": "friendly",
    "classic_style": "classic",
    "cartoony_style": "cartoony",
    "robot_style": "robot",
    "dot_style": "robot",
    "sinister_style": "sinister",
    "sleepy_style": "sleepy",
}
STYLE_ALIASES: dict[str, str] = {
    "cartoon": "cartoony",
    "row_body": "robot",
    "dot": "robot",
    "big_dot": "robot",
    "slit": "sinister",
    "slits": "sinister",
    "cat_eye": "sinister",
    "red": "sinister",
    "steel": "sleepy",
}
EMOTION_ALIASES: dict[str, str] = {
    "fear": "afraid",
    "frighten": "afraid",
    "frightened": "afraid",
    "scared": "afraid",
}
MOUTH_SHAPE_ALIASES: dict[str, str] = {
    "smirk": "smirk_right",
    "teeth": "grimace",
    "sinister": "sneer",
}
MOUTH_STYLE_ALIASES: dict[str, str] = {
    "humanistic": "human",
}


def _optional_float(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float, str)):
        return float(value)
    return default


def _clamp_float(value: object, low: float, high: float) -> float:
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"Expected a number, got {type(value).__name__}")
    number = float(value)
    return min(max(number, low), high)


class SetEyes(Tool):
    """Control the optional ESP32 eyes display."""

    name = "set_eyes"
    description = "Control the optional ESP32 face displays with high-level eye and mouth cues."
    needs_response = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(EYE_ACTIONS),
                "description": "One-shot action. Use *_style actions only when the user asks to change the rendered eye type.",
            },
            "emotion": {
                "type": "string",
                "enum": list(EYE_EMOTIONS),
                "description": "Longer-lived eye emotion preset.",
            },
            "expression": {
                "type": "string",
                "enum": list(EYE_EXPRESSIONS),
                "description": "Short expression overlay.",
            },
            "beat": {
                "type": "string",
                "enum": list(EYE_BEATS),
                "description": "Scripted idle beat to play immediately.",
            },
            "style": {
                "type": "string",
                "enum": list(EYE_STYLES),
                "description": "Persistent renderer style. Use robot, dot, or big_dot for the simple big-dot eyes; do not use emotion=robotic for renderer style.",
            },
            "duration_s": {
                "type": "number",
                "description": "Expression or gaze hold duration in seconds. Use 0 for a held manual gaze.",
            },
            "move_ms": {
                "type": "integer",
                "description": "Manual gaze movement time in milliseconds.",
            },
            "gaze": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "required": ["x", "y"],
                "additionalProperties": False,
                "description": "Manual gaze target. Use x/y in -1..1 for normalized gaze, or include z for full 3D firmware units.",
            },
            "brightness": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Software brightness, from 0.0 to 1.0.",
            },
            "flip": {
                "type": "boolean",
                "description": "Whether to use flipped eye orientation.",
            },
            "mouth_shape": {
                "type": "string",
                "enum": list(MOUTH_SHAPES),
                "description": "Mouth shape for the optional third display.",
            },
            "mouth_style": {
                "type": "string",
                "enum": list(MOUTH_STYLES),
                "description": "Mouth renderer style.",
            },
            "mouth_talking": {
                "type": "boolean",
                "description": "Whether the mouth should chatter with energy-based speech animation.",
            },
            "mouth_energy": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Speech animation intensity for the mouth.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        """Control the optional ESP32 eyes display."""
        eyes_controller = deps.eyes_controller
        if eyes_controller is None:
            return {"error": "ESP32 eyes are not configured"}

        logger.info("Tool call: set_eyes args=%s", kwargs)
        results: list[dict[str, object]] = []

        action = str(kwargs.get("action") or "").strip().lower()
        if action == "status":
            results.append(await asyncio.to_thread(eyes_controller.get_state))
        elif action == "release" or action == "wake":
            results.append(await asyncio.to_thread(eyes_controller.release))
        elif action == "sleep":
            results.append(
                await asyncio.to_thread(eyes_controller.sleep, _optional_float(kwargs.get("duration_s"), 0.0))
            )
        elif action == "blink":
            results.append(await asyncio.to_thread(eyes_controller.blink, "both"))
        elif action == "double_blink":
            results.append(await asyncio.to_thread(eyes_controller.control, {"blink": True, "double": True}))
        elif action == "left_wink":
            results.append(await asyncio.to_thread(eyes_controller.wink, "left"))
        elif action == "right_wink":
            results.append(await asyncio.to_thread(eyes_controller.wink, "right"))
        elif action in STYLE_ACTIONS:
            results.append(await asyncio.to_thread(eyes_controller.style, STYLE_ACTIONS[action]))
        elif action:
            return {"error": f"Unknown eye action: {action}"}

        emotion = str(kwargs.get("emotion") or "").strip().lower()
        if emotion:
            emotion = EMOTION_ALIASES.get(emotion, emotion)
            duration_s = _optional_float(kwargs.get("duration_s"), DEFAULT_EMOTION_DURATION_S)
            results.append(await asyncio.to_thread(eyes_controller.emotion, emotion, duration_s))

        expression = str(kwargs.get("expression") or "").strip().lower()
        if expression:
            expression = EMOTION_ALIASES.get(expression, expression)
            duration_s = _optional_float(kwargs.get("duration_s"), DEFAULT_EXPRESSION_DURATION_S)
            results.append(await asyncio.to_thread(eyes_controller.expression, expression, duration_s))

        beat = str(kwargs.get("beat") or "").strip().lower()
        if beat:
            results.append(await asyncio.to_thread(eyes_controller.beat, beat))

        style = str(kwargs.get("style") or "").strip().lower()
        if style:
            style = STYLE_ALIASES.get(style, style)
            results.append(await asyncio.to_thread(eyes_controller.style, style))

        control_payload: dict[str, object] = {}
        if "brightness" in kwargs:
            control_payload["brightness"] = _clamp_float(kwargs["brightness"], 0.0, 1.0)
        if "flip" in kwargs:
            control_payload["flip"] = bool(kwargs["flip"])
        mouth_payload: dict[str, object] = {}
        mouth_shape = str(kwargs.get("mouth_shape") or "").strip().lower()
        if mouth_shape:
            mouth_payload["shape"] = MOUTH_SHAPE_ALIASES.get(mouth_shape, mouth_shape)
            mouth_payload["duration"] = _optional_float(kwargs.get("duration_s"), DEFAULT_MOUTH_DURATION_S)
        mouth_style = str(kwargs.get("mouth_style") or "").strip().lower()
        if mouth_style:
            mouth_payload["style"] = MOUTH_STYLE_ALIASES.get(mouth_style, mouth_style)
        if "mouth_talking" in kwargs:
            mouth_payload["talking"] = bool(kwargs["mouth_talking"])
            mouth_payload["duration"] = _optional_float(kwargs.get("duration_s"), DEFAULT_MOUTH_DURATION_S)
        if "mouth_energy" in kwargs:
            mouth_payload["energy"] = _clamp_float(kwargs["mouth_energy"], 0.0, 1.0)
        if mouth_payload:
            control_payload["mouth"] = mouth_payload
        if isinstance(kwargs.get("gaze"), dict):
            gaze = kwargs["gaze"]
            gaze_payload: dict[str, object] = {
                "x": _optional_float(gaze.get("x"), 0.0),
                "y": _optional_float(gaze.get("y"), 0.0),
                "duration": _optional_float(kwargs.get("duration_s"), DEFAULT_GAZE_DURATION_S),
            }
            if gaze.get("z") is not None:
                gaze_payload["z"] = _optional_float(gaze.get("z"), 500.0)
            if kwargs.get("move_ms") is not None:
                gaze_payload["move_ms"] = int(_optional_float(kwargs.get("move_ms"), 160.0))
            control_payload["gaze"] = gaze_payload
        if control_payload:
            results.append(await asyncio.to_thread(eyes_controller.control, control_payload))

        if not results:
            results.append(await asyncio.to_thread(eyes_controller.get_state))

        errors = [result["error"] for result in results if "error" in result]
        if errors:
            return {"error": "; ".join(str(error) for error in errors), "results": results}
        return {"status": "ok", "results": results}
