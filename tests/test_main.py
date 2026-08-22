"""Tests for app-level runtime behavior."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import reachy_mini_conversation_app.main as main_mod


def test_inactivity_timeout_thread_goes_to_sleep() -> None:
    """The watchdog should use the shared sleep shutdown path once activity is too old."""
    stream_manager = SimpleNamespace(seconds_since_activity=lambda: 10.0, close=MagicMock())
    go_to_sleep = MagicMock(return_value={"status": "sleeping"})

    thread = main_mod._start_inactivity_timeout_thread(
        timeout_minutes=0.0001,
        stream_manager=stream_manager,
        logger=MagicMock(),
        app_stop_event=threading.Event(),
        go_to_sleep=go_to_sleep,
    )

    thread.join(timeout=1.0)
    assert not thread.is_alive()
    go_to_sleep.assert_called_once_with()
    stream_manager.close.assert_not_called()


def test_inactivity_timeout_thread_closes_stream_manager_without_sleep_callback() -> None:
    """The watchdog should still close the stream when no sleep callback is available."""
    stream_manager = SimpleNamespace(seconds_since_activity=lambda: 10.0, close=MagicMock())

    thread = main_mod._start_inactivity_timeout_thread(
        timeout_minutes=0.0001,
        stream_manager=stream_manager,
        logger=MagicMock(),
        app_stop_event=threading.Event(),
    )

    thread.join(timeout=1.0)
    assert not thread.is_alive()
    stream_manager.close.assert_called_once_with()


def test_stop_optional_chassis_logs_error_result() -> None:
    """Optional chassis stop failures should not raise into lifecycle paths."""
    chassis_controller = SimpleNamespace(stop=MagicMock(return_value={"error": "offline"}))
    logger = MagicMock()

    main_mod._stop_optional_chassis(chassis_controller, logger, "sleep")

    chassis_controller.stop.assert_called_once_with()
    logger.warning.assert_called_once_with("ESP32 chassis stop during %s reported: %s", "sleep", "offline")


def test_stop_optional_chassis_catches_exception() -> None:
    """Unexpected optional chassis stop errors should remain best-effort."""
    chassis_controller = SimpleNamespace(stop=MagicMock(side_effect=RuntimeError("boom")))
    logger = MagicMock()

    main_mod._stop_optional_chassis(chassis_controller, logger, "shutdown")

    chassis_controller.stop.assert_called_once_with()
    logger.warning.assert_called_once()


def test_cue_optional_eyes_catches_exception() -> None:
    """Optional eye cue failures should not raise into lifecycle paths."""
    eyes_controller = SimpleNamespace(cue=MagicMock(side_effect=RuntimeError("boom")))
    logger = MagicMock()

    main_mod._cue_optional_eyes(eyes_controller, logger, "sleep", {"duration": 0})

    eyes_controller.cue.assert_called_once_with("sleep", {"duration": 0})
    logger.warning.assert_called_once()
