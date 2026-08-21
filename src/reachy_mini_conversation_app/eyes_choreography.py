import time
import logging
import threading
from typing import Any


logger = logging.getLogger(__name__)

_HEAD_GAZE_BY_DIRECTION: dict[str, tuple[float, float]] = {
    "left": (-0.8, 0.0),
    "right": (0.8, 0.0),
    "up": (0.0, -0.45),
    "down": (0.0, 0.45),
    "front": (0.0, 0.0),
}


def cue_eyes(deps: Any, action: str, payload: dict[str, object] | None = None) -> None:
    """Send a best-effort cue to optional eye hardware."""
    eyes_controller = getattr(deps, "eyes_controller", None)
    if eyes_controller is None:
        return
    try:
        eyes_controller.cue(action, payload)
    except Exception:
        logger.debug("Eye choreography cue failed", exc_info=True)


def cue_conversation_listening(deps: Any) -> None:
    """Cue eyes for active listening."""
    cue_eyes(deps, "control", {"emotion": "curious", "mouth": {"shape": "neutral", "talking": False, "duration": 1.0}})


def cue_conversation_speaking(deps: Any) -> None:
    """Cue eyes for assistant speech."""
    cue_eyes(
        deps,
        "control",
        {"emotion": "happy", "mouth": {"shape": "open", "talking": True, "energy": 0.55, "duration": 2.4}},
    )


def cue_conversation_idle(deps: Any) -> None:
    """Release eyes back to autonomous idle."""
    cue_eyes(deps, "release")


def cue_body_emotion(deps: Any, eye_emotion: str | None) -> None:
    """Cue eyes for a resolved body emotion."""
    if eye_emotion is not None:
        cue_eyes(deps, "emotion", {"name": eye_emotion})


def cue_dance(deps: Any) -> None:
    """Cue eyes for a queued dance."""
    cue_eyes(deps, "beat", {"name": "goofy"})


def cue_head_direction(deps: Any, direction: str, duration_s: float, move_ms: int = 250) -> None:
    """Cue gaze to match a queued head direction."""
    gaze = _HEAD_GAZE_BY_DIRECTION.get(direction)
    if gaze is None:
        return
    cue_eyes(
        deps,
        "control",
        {
            "gaze": {
                "x": gaze[0],
                "y": gaze[1],
                "duration": max(duration_s, 0.5),
                "move_ms": move_ms,
            }
        },
    )


def cue_sweep(deps: Any) -> None:
    """Cue eyes for a sweep-look routine."""
    eyes_controller = getattr(deps, "eyes_controller", None)
    if eyes_controller is None:
        return

    def run_sequence() -> None:
        try:
            eyes_controller.emotion("focused", 14.0)
            time.sleep(0.05)
            eyes_controller.control({"gaze": {"x": -1.0, "y": 0.0, "duration": 4.0, "move_ms": 450}})
            time.sleep(3.95)
            eyes_controller.control({"gaze": {"x": 0.0, "y": 0.0, "duration": 3.0, "move_ms": 400}})
            time.sleep(3.0)
            eyes_controller.control({"gaze": {"x": 1.0, "y": 0.0, "duration": 4.0, "move_ms": 450}})
            time.sleep(4.0)
            eyes_controller.control({"gaze": {"x": 0.0, "y": 0.0, "duration": 3.0, "move_ms": 400}})
        except Exception:
            logger.debug("Eye sweep cue failed", exc_info=True)

    threading.Thread(target=run_sequence, daemon=True, name="esp32-eyes-sweep-cue").start()


def cue_sleep(deps: Any, duration_s: float = 0.0) -> None:
    """Cue eyes for sleep."""
    cue_eyes(deps, "sleep", {"duration": duration_s})


def cue_release(deps: Any) -> None:
    """Release any app-driven eye override."""
    cue_eyes(deps, "release")
