from unittest.mock import MagicMock, call
from collections.abc import Callable

import pytest

import reachy_mini_conversation_app.eyes_choreography as eyes_choreography
from reachy_mini_conversation_app.tools.core_tools import ToolDependencies
from reachy_mini_conversation_app.eyes_choreography import (
    cue_dance,
    cue_sleep,
    cue_release,
    cue_body_emotion,
    cue_head_direction,
    cue_conversation_idle,
    cue_conversation_speaking,
    cue_conversation_listening,
)


def _deps_with_eyes() -> tuple[ToolDependencies, MagicMock]:
    eyes_controller = MagicMock()
    deps = ToolDependencies(
        reachy_mini=MagicMock(),
        movement_manager=MagicMock(),
        eyes_controller=eyes_controller,
    )
    return deps, eyes_controller


def test_conversation_choreography_cues_eye_states() -> None:
    """Conversation state changes should cue matching eye states."""
    deps, eyes_controller = _deps_with_eyes()

    cue_conversation_listening(deps)
    cue_conversation_speaking(deps)
    cue_conversation_idle(deps)

    assert eyes_controller.cue.call_args_list == [
        call("control", {"emotion": "curious", "mouth": {"shape": "neutral", "talking": False, "duration": 1.0}}),
        call(
            "control",
            {"emotion": "happy", "mouth": {"shape": "open", "talking": True, "energy": 0.55, "duration": 2.4}},
        ),
        call("release", None),
    ]


def test_body_emotion_choreography_cues_matching_eye_emotion() -> None:
    """Resolved body emotions should cue matching eye emotions."""
    deps, eyes_controller = _deps_with_eyes()

    cue_body_emotion(deps, "afraid")
    cue_body_emotion(deps, None)

    eyes_controller.cue.assert_called_once_with("emotion", {"name": "afraid"})


def test_head_direction_choreography_cues_matching_gaze() -> None:
    """Head direction moves should cue matching gaze targets."""
    deps, eyes_controller = _deps_with_eyes()

    cue_head_direction(deps, "right", 1.2)

    eyes_controller.cue.assert_called_once_with(
        "control",
        {"gaze": {"x": 0.8, "y": 0.0, "duration": 1.2, "move_ms": 250}},
    )


def test_routine_choreography_cues_eye_beats_and_release() -> None:
    """Routine cues should map to firmware eye beats and release."""
    deps, eyes_controller = _deps_with_eyes()

    cue_dance(deps)
    cue_sleep(deps)
    cue_release(deps)

    assert eyes_controller.cue.call_args_list == [
        call("beat", {"name": "goofy"}),
        call("sleep", {"duration": 0.0}),
        call("release", None),
    ]


def test_sweep_choreography_tracks_full_head_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sweep choreography should keep eyes involved across the full head routine."""
    deps, eyes_controller = _deps_with_eyes()
    sleep_delays: list[float] = []

    class ImmediateThread:
        def __init__(self, target: Callable[[], None], daemon: bool, name: str) -> None:
            self._target = target

        def start(self) -> None:
            self._target()

    monkeypatch.setattr(eyes_choreography.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(eyes_choreography.time, "sleep", sleep_delays.append)

    eyes_choreography.cue_sweep(deps)

    eyes_controller.emotion.assert_called_once_with("focused", 14.0)
    assert eyes_controller.control.call_args_list == [
        call({"gaze": {"x": -1.0, "y": 0.0, "duration": 4.0, "move_ms": 450}}),
        call({"gaze": {"x": 0.0, "y": 0.0, "duration": 3.0, "move_ms": 400}}),
        call({"gaze": {"x": 1.0, "y": 0.0, "duration": 4.0, "move_ms": 450}}),
        call({"gaze": {"x": 0.0, "y": 0.0, "duration": 3.0, "move_ms": 400}}),
    ]
    assert sleep_delays == [0.05, 3.95, 3.0, 4.0]
