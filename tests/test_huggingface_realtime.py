import time
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import reachy_mini_conversation_app.conversation_handler as conv_mod
import reachy_mini_conversation_app.huggingface_realtime as hf_mod
from reachy_mini_conversation_app.config import config, get_default_voice
from reachy_mini_conversation_app.tools.core_tools import ToolDependencies
from reachy_mini_conversation_app.huggingface_realtime import HuggingFaceRealtimeHandler
from reachy_mini_conversation_app.tools.background_tool_manager import ToolState, ToolNotification


HF_DEFAULT_VOICE = get_default_voice()


class _FakeEvent:
    """A minimal realtime event: a `type` plus arbitrary attributes."""

    def __init__(self, event_type: str, **fields: Any) -> None:
        """Store the event type and any extra attributes."""
        self.type = event_type
        self.__dict__.update(fields)


def _make_fake_realtime_client(
    *,
    events: tuple[_FakeEvent, ...] = (),
    captured_update: dict[str, Any] | None = None,
    captured_connect: dict[str, Any] | None = None,
) -> Any:
    """Build a fake AsyncOpenAI-shaped client whose realtime session yields `events`.

    When given, `captured_update`/`captured_connect` record the kwargs passed to
    `session.update(...)` / `realtime.connect(...)`.
    """

    class FakeSession:
        async def update(self, **kwargs: Any) -> None:
            if captured_update is not None:
                captured_update.update(kwargs)

    class FakeNoop:
        async def append(self, **_kw: Any) -> None:
            pass

        async def create(self, **_kw: Any) -> None:
            pass

        async def cancel(self, **_kw: Any) -> None:
            pass

    class FakeConversation:
        item = FakeNoop()

    class FakeConn:
        session = FakeSession()
        input_audio_buffer = FakeNoop()
        conversation = FakeConversation()
        response = FakeNoop()

        def __init__(self) -> None:
            self._events = iter(events)

        async def __aenter__(self) -> "FakeConn":
            return self

        async def __aexit__(self, *_args: Any) -> bool:
            return False

        async def close(self) -> None:
            pass

        def __aiter__(self) -> "FakeConn":
            return self

        async def __anext__(self) -> _FakeEvent:
            try:
                return next(self._events)
            except StopIteration:
                raise StopAsyncIteration

    class FakeRealtime:
        def connect(self, **kwargs: Any) -> FakeConn:
            if captured_connect is not None:
                captured_connect.update(kwargs)
            return FakeConn()

    class FakeClient:
        realtime = FakeRealtime()

    return FakeClient()


def _fake_openai_client(captured_kwargs: dict[str, Any]) -> type:
    """Return a fake AsyncOpenAI class that records its constructor kwargs."""

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

    return FakeClient


def _fake_allocator(
    connect_url: str,
    posts: list[tuple[str, dict[str, str] | None, dict[str, str] | None]],
) -> type:
    """Return a fake httpx.AsyncClient that records allocator requests."""

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"session_id": "session-123", "connect_url": connect_url}

    class FakeAsyncClient:
        def __init__(self, **_kw: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

        async def post(
            self,
            url: str,
            headers: dict[str, str] | None = None,
            json: dict[str, str] | None = None,
        ) -> FakeResponse:
            posts.append((url, headers, json))
            return FakeResponse()

    return FakeAsyncClient


@pytest.mark.asyncio
async def test_partial_transcription_uses_latest_snapshot(monkeypatch: Any) -> None:
    """Partial transcription snapshots should replace older snapshots for the same item."""
    monkeypatch.setattr(hf_mod, "get_session_instructions", lambda _instance_path=None: "test")
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: "Aiden")
    monkeypatch.setattr(hf_mod, "get_tool_specs", lambda: [])

    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))
    handler.client = _make_fake_realtime_client(
        events=(
            _FakeEvent("conversation.item.input_audio_transcription.delta", item_id="item-1", delta="Hey"),
            _FakeEvent(
                "conversation.item.input_audio_transcription.delta", item_id="item-1", delta="Hey, how are you?"
            ),
        )
    )
    monkeypatch.setattr(type(handler.tool_manager), "start_up", MagicMock())
    monkeypatch.setattr(type(handler.tool_manager), "shutdown", AsyncMock())

    await handler._run_realtime_session()

    assert handler.input_transcript_chunks_by_item.item_id == "item-1"
    assert handler.input_transcript_chunks_by_item.deltas == ["Hey, how are you?"]


@pytest.mark.asyncio
async def test_emit_skips_idle_signal_while_response_active(monkeypatch: Any) -> None:
    """Idle tools should not trigger while a response is still active."""
    movement_manager = MagicMock()
    movement_manager.is_idle.return_value = True
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=movement_manager)
    handler = HuggingFaceRealtimeHandler(deps)
    handler.last_activity_time = time.monotonic() - (handler.IDLE_BEHAVIOR_THRESHOLD_S + 10.0)
    handler._response_done_event.clear()

    send_idle_signal = AsyncMock()
    monkeypatch.setattr(handler, "send_idle_signal", send_idle_signal)
    monkeypatch.setattr(conv_mod, "wait_for_item", AsyncMock(return_value=None))

    result = await handler.emit()

    assert result is None
    send_idle_signal.assert_not_awaited()


@pytest.mark.asyncio
async def test_parallel_tool_calls_trigger_single_response(monkeypatch: Any) -> None:
    """Parallel tool calls in one turn should yield one response, not one per completed tool."""
    monkeypatch.setattr(hf_mod, "get_session_instructions", lambda _instance_path=None: "test")
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: "Aiden")
    monkeypatch.setattr(hf_mod, "get_tool_specs", lambda: [])

    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))
    handler.connection = AsyncMock()
    handler.output_queue = asyncio.Queue()
    monkeypatch.setattr(handler, "_wait_for_response_done_before_tool_result", AsyncMock(return_value=True))
    create = AsyncMock()
    monkeypatch.setattr(handler, "_safe_response_create", create)

    handler._in_flight_tool_calls = {"call_a", "call_b"}

    def _completed(call_id: str) -> ToolNotification:
        return ToolNotification(
            id=call_id,
            tool_name="test__parallel_probe",
            is_idle_tool_call=False,
            status=ToolState.COMPLETED,
            result={"ok": True},
        )

    await handler._handle_tool_result(_completed("call_a"))
    assert create.await_count == 0

    await handler._handle_tool_result(_completed("call_b"))
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_camera_tool_result_emits_browser_image_metadata(monkeypatch: Any) -> None:
    """Camera captures should be available to the web UI without exposing base64 to the model result."""
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))
    handler.connection = AsyncMock()
    handler.output_queue = asyncio.Queue()
    handler._in_flight_tool_calls = {"call_camera"}
    monkeypatch.setattr(handler, "_wait_for_response_done_before_tool_result", AsyncMock(return_value=True))
    monkeypatch.setattr(handler, "_safe_response_create", AsyncMock())

    await handler._handle_tool_result(
        ToolNotification(
            id="call_camera",
            tool_name="camera",
            is_idle_tool_call=False,
            status=ToolState.COMPLETED,
            result={"b64_im": "abc123"},
        )
    )

    model_output = await handler.output_queue.get()
    camera_output = await handler.output_queue.get()

    assert "abc123" not in model_output.args[0]["content"]
    assert camera_output.args[0] == {
        "role": "camera",
        "content": "Captured camera image.",
        "image_b64": "abc123",
        "mime_type": "image/jpeg",
        "jpeg_bytes": 4,
    }


@pytest.mark.asyncio
async def test_show_image_tool_result_emits_browser_image_metadata(monkeypatch: Any) -> None:
    """Displayed web images should reach the UI image preview."""
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))
    handler.connection = AsyncMock()
    handler.output_queue = asyncio.Queue()
    handler._in_flight_tool_calls = {"call_image"}
    monkeypatch.setattr(handler, "_wait_for_response_done_before_tool_result", AsyncMock(return_value=True))
    monkeypatch.setattr(handler, "_safe_response_create", AsyncMock())

    await handler._handle_tool_result(
        ToolNotification(
            id="call_image",
            tool_name="show_image",
            is_idle_tool_call=False,
            status=ToolState.COMPLETED,
            result={"status": "ok", "image_url": "https://example.com/reachy.jpg", "source": "web", "title": "Reachy"},
        )
    )

    await handler.output_queue.get()
    image_output = await handler.output_queue.get()

    assert image_output.args[0] == {
        "role": "image",
        "content": "Displayed image.",
        "image_url": "https://example.com/reachy.jpg",
        "source": "web",
        "title": "Reachy",
    }


@pytest.mark.asyncio
async def test_speech_started_during_assistant_playback_does_not_flush(monkeypatch: Any) -> None:
    """Echo-triggered VAD should not clear queued assistant audio."""
    monkeypatch.setattr(hf_mod, "get_session_instructions", lambda _instance_path=None: "test")
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: default)
    monkeypatch.setattr(hf_mod, "get_session_greeting_prompt", lambda: "")
    monkeypatch.setattr(hf_mod, "get_tool_specs", lambda: [])

    movement_manager = MagicMock()
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=movement_manager))
    clear_queue = MagicMock()
    handler._clear_queue = clear_queue
    handler._playback_active = lambda: True
    handler.client = _make_fake_realtime_client(events=(_FakeEvent("input_audio_buffer.speech_started"),))
    monkeypatch.setattr(type(handler.tool_manager), "start_up", MagicMock())
    monkeypatch.setattr(type(handler.tool_manager), "shutdown", AsyncMock())

    await handler._run_realtime_session()

    clear_queue.assert_not_called()
    movement_manager.set_listening.assert_not_called()


@pytest.mark.asyncio
async def test_speech_started_without_assistant_playback_flushes(monkeypatch: Any) -> None:
    """Normal user speech should still clear stale playback and enter listening."""
    monkeypatch.setattr(hf_mod, "get_session_instructions", lambda _instance_path=None: "test")
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: default)
    monkeypatch.setattr(hf_mod, "get_session_greeting_prompt", lambda: "")
    monkeypatch.setattr(hf_mod, "get_tool_specs", lambda: [])

    movement_manager = MagicMock()
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=movement_manager))
    clear_queue = MagicMock()
    handler._clear_queue = clear_queue
    handler._playback_active = lambda: False
    handler.client = _make_fake_realtime_client(events=(_FakeEvent("input_audio_buffer.speech_started"),))
    monkeypatch.setattr(type(handler.tool_manager), "start_up", MagicMock())
    monkeypatch.setattr(type(handler.tool_manager), "shutdown", AsyncMock())

    await handler._run_realtime_session()

    clear_queue.assert_called_once()
    movement_manager.set_listening.assert_called_once_with(True)


def test_handler_uses_hf_startup_voice_at_startup(monkeypatch: Any) -> None:
    """Hugging Face startup should restore persisted HF voices."""
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()),
        startup_voice="Aiden",
    )

    assert handler.get_current_voice() == "Aiden"


def test_manual_eye_holdoff_skips_automatic_cues() -> None:
    """Explicit set_eyes calls should not be immediately undone by automatic cues."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )

    handler._hold_automatic_eye_cues()
    handler._cue_eyes("release")

    eyes_controller.cue.assert_not_called()


def test_automatic_eye_cues_resume_after_holdoff() -> None:
    """Automatic cues should resume after the manual eye-control window expires."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )
    handler._manual_eye_cue_holdoff_until = time.monotonic() - 1.0

    handler._cue_eyes("release")

    eyes_controller.cue.assert_called_once_with("release", None)


@pytest.mark.asyncio
async def test_sweep_tool_eye_cue_holdoff_skips_automatic_release() -> None:
    """Sweep eye choreography should not be immediately cancelled by response release."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )

    await handler._handle_tool_result(
        ToolNotification(
            id="call_sweep",
            tool_name="sweep_look",
            is_idle_tool_call=False,
            status=ToolState.COMPLETED,
            result={"status": "sweeping look left-right-center, total 14.0s"},
        )
    )
    handler._cue_eyes("release")

    eyes_controller.cue.assert_not_called()


def test_transcript_eye_expression_request_cues_controller() -> None:
    """Obvious spoken eye-expression requests should work without model tool choice."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )

    handler._cue_eyes_from_transcript("I want you to look suspicious.")
    handler._cue_eyes("release")

    eyes_controller.cue.assert_called_once_with("expression", {"name": "suspicious", "duration": 6.0})


def test_transcript_without_eye_intent_does_not_cue_controller() -> None:
    """Eye expression words in ordinary speech should not become hardware commands."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )

    handler._cue_eyes_from_transcript("That seems suspicious.")

    eyes_controller.cue.assert_not_called()


def test_transcript_eye_gaze_request_cues_controller() -> None:
    """Simple spoken gaze requests should map to normalized eye API coordinates."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )

    handler._cue_eyes_from_transcript("Aim your eyes up and left.")

    eyes_controller.cue.assert_called_once_with(
        "control",
        {"gaze": {"x": -0.8, "y": -0.45, "duration": 5.0, "move_ms": 250}},
    )


def test_transcript_full_range_eye_gaze_request_cues_controller() -> None:
    """Full-range gaze phrases should use the edge of the normalized API."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )

    handler._cue_eyes_from_transcript("Aim your gaze all the way to the right.")

    eyes_controller.cue.assert_called_once_with(
        "control",
        {"gaze": {"x": 1.0, "y": 0.0, "duration": 5.0, "move_ms": 250}},
    )


def test_transcript_eye_style_request_cues_controller() -> None:
    """Simple spoken eye-style requests should map aliases to firmware styles."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )

    handler._cue_eyes_from_transcript("Switch your eye style to big dot.")

    eyes_controller.cue.assert_called_once_with("style", {"name": "robot"})


def test_transcript_eye_style_asr_alias_cues_controller() -> None:
    """Likely ASR mistakes in eye-style requests should map to intended styles."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )

    handler._cue_eyes_from_transcript("Can you set your eye style to row body?")

    eyes_controller.cue.assert_called_once_with("style", {"name": "robot"})


@pytest.mark.parametrize(
    "transcript",
    [
        "Okay, now make them look sinister.",
        "Can you make them slits?",
    ],
)
def test_transcript_sinister_eye_style_requests_cue_controller(transcript: str) -> None:
    """Sinister/slit phrasing should map to the slit renderer style."""
    eyes_controller = MagicMock()
    handler = HuggingFaceRealtimeHandler(
        ToolDependencies(
            reachy_mini=MagicMock(),
            movement_manager=MagicMock(),
            eyes_controller=eyes_controller,
        )
    )

    handler._cue_eyes_from_transcript(transcript)

    eyes_controller.cue.assert_called_once_with("style", {"name": "sinister"})


def test_handler_ignores_unsupported_hf_profile_voice(monkeypatch: Any) -> None:
    """Unsupported profile voices should not be sent to the Hugging Face backend."""
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: "cedar")

    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))

    assert handler.get_current_voice() == HF_DEFAULT_VOICE
    session = handler._get_session_config([])
    assert session["audio"]["output"]["voice"] == HF_DEFAULT_VOICE


def test_handler_normalizes_hf_voice_case(monkeypatch: Any) -> None:
    """Lowercase Hugging Face speaker names should resolve to the curated UI value."""
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: "serena")

    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))

    assert handler.get_current_voice() == "Serena"


@pytest.mark.asyncio
async def test_run_realtime_session_uses_default_voice_for_lb_allocated_sessions(monkeypatch: Any) -> None:
    """Use the backend default speaker when no profile voice is selected for the hf LB."""
    monkeypatch.setattr(hf_mod, "get_session_instructions", lambda _instance_path=None: "test")
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: default)
    monkeypatch.setattr(hf_mod, "get_tool_specs", lambda: [])
    monkeypatch.setattr(config, "HF_REALTIME_SESSION_URL", "https://lb.example.test/session")

    captured_update: dict[str, Any] = {}
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))
    handler.client = _make_fake_realtime_client(captured_update=captured_update)

    await handler._run_realtime_session()

    session = captured_update["session"]
    # HF at 16 kHz passes None so the backend uses its optimal default (16 kHz).
    assert session["audio"]["input"]["format"]["rate"] is None
    assert session["audio"]["output"]["format"]["rate"] is None
    assert session["audio"]["input"]["turn_detection"]["interrupt_response"] is False
    assert session["audio"]["input"]["transcription"]["language"] == "en"
    assert session["audio"]["output"]["voice"] == HF_DEFAULT_VOICE


def test_huggingface_session_uses_configured_transcription_language(monkeypatch: Any) -> None:
    """Hugging Face realtime sessions should forward the configured transcription language."""
    monkeypatch.setattr(config, "REALTIME_TRANSCRIPTION_LANGUAGE", "zh")
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))

    session = handler._get_session_config([])

    assert session["audio"]["input"]["transcription"]["language"] == "zh"


@pytest.mark.asyncio
async def test_run_realtime_session_passes_allocated_session_query(monkeypatch: Any) -> None:
    """Hugging Face sessions must forward the allocated session token to the websocket connect call."""
    monkeypatch.setattr(hf_mod, "get_session_instructions", lambda _instance_path=None: "test")
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: default)
    monkeypatch.setattr(hf_mod, "get_tool_specs", lambda: [])
    monkeypatch.setattr(config, "HF_REALTIME_CONNECTION_MODE", "deployed")

    captured_connect: dict[str, Any] = {}
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))
    handler.client = _make_fake_realtime_client(captured_connect=captured_connect)
    handler._realtime_connect_query = {"session_token": "abc123"}

    await handler._run_realtime_session()

    assert "model" not in captured_connect
    assert captured_connect["extra_query"] == {"session_token": "abc123"}


@pytest.mark.asyncio
async def test_run_realtime_session_uses_longer_local_websocket_heartbeat(monkeypatch: Any) -> None:
    """Local realtime bridge sessions should tolerate slow local TTS responses."""
    monkeypatch.setattr(hf_mod, "get_session_instructions", lambda _instance_path=None: "test")
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: default)
    monkeypatch.setattr(hf_mod, "get_tool_specs", lambda: [])
    monkeypatch.setattr(config, "HF_REALTIME_CONNECTION_MODE", "local")
    monkeypatch.setenv("HF_REALTIME_WS_PING_INTERVAL_S", "61")
    monkeypatch.setenv("HF_REALTIME_WS_PING_TIMEOUT_S", "62")

    captured_connect: dict[str, Any] = {}
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))
    handler.client = _make_fake_realtime_client(captured_connect=captured_connect)

    await handler._run_realtime_session()

    assert captured_connect["websocket_connection_options"] == {"ping_interval": 61.0, "ping_timeout": 62.0}


@pytest.mark.parametrize(("hf_token", "expected_api_key"), [(None, "DUMMY"), ("hf-secret", "hf-secret")])
@pytest.mark.asyncio
async def test_build_realtime_client_local_uses_explicit_hf_token_only(
    monkeypatch: Any,
    hf_token: str | None,
    expected_api_key: str,
) -> None:
    """Local websocket mode must never forward cached Hugging Face credentials."""
    client_kwargs: dict[str, Any] = {}

    def _no_allocator(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("session allocator should not be called in direct websocket mode")

    monkeypatch.setattr(hf_mod, "AsyncOpenAI", _fake_openai_client(client_kwargs))
    monkeypatch.setattr(hf_mod.httpx, "AsyncClient", _no_allocator)
    monkeypatch.setattr(config, "HF_REALTIME_CONNECTION_MODE", "local")
    monkeypatch.setattr(config, "HF_REALTIME_SESSION_URL", "https://lb.example.test/session")
    monkeypatch.setattr(config, "HF_TOKEN", hf_token)
    monkeypatch.setattr(hf_mod, "get_token", lambda: "hf-cached")
    monkeypatch.setattr(
        config,
        "HF_REALTIME_WS_URL",
        "ws://127.0.0.1:8765/v1/realtime?session_token=abc123&model=ignored-by-sdk",
    )

    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))

    client = await handler._build_realtime_client()

    assert client is not None
    assert client_kwargs["api_key"] == expected_api_key
    assert client_kwargs["base_url"] == "http://127.0.0.1:8765/v1"
    assert client_kwargs["websocket_base_url"] == "ws://127.0.0.1:8765/v1"
    assert handler._realtime_connect_query == {"session_token": "abc123"}


@pytest.mark.parametrize(
    (
        "hf_token",
        "cached_token",
        "hardware_id",
        "status_error",
        "expected_header",
        "expected_api_key",
        "expected_payload",
    ),
    [
        (
            "hf-secret",
            "hf-cached",
            "0123456789abcdef",
            None,
            {
                "User-Agent": "reachy-mini-conversation-app",
                "X-Reachy-Mini-Authorization": "Bearer hf-secret",
            },
            "hf-secret",
            {"hardware_id": "0123456789abcdef"},
        ),
        (
            None,
            "hf-cached",
            None,
            None,
            {
                "User-Agent": "reachy-mini-conversation-app",
                "X-Reachy-Mini-Authorization": "Bearer hf-cached",
            },
            "hf-cached",
            {},
        ),
        (None, None, None, None, {"User-Agent": "reachy-mini-conversation-app"}, "DUMMY", {}),
        (
            None,
            None,
            None,
            TimeoutError("status unavailable"),
            {"User-Agent": "reachy-mini-conversation-app"},
            "DUMMY",
            {},
        ),
    ],
)
@pytest.mark.asyncio
async def test_build_realtime_client_deployed_resolves_hf_token(
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
    hf_token: str | None,
    cached_token: str | None,
    hardware_id: str | None,
    status_error: Exception | None,
    expected_header: dict[str, str],
    expected_api_key: str,
    expected_payload: dict[str, str],
) -> None:
    """Deployed allocation reports available credentials and robot identity."""
    client_kwargs: dict[str, Any] = {}
    posts: list[tuple[str, dict[str, str] | None, dict[str, str] | None]] = []
    connect_url = "wss://hf.example.test/v1/realtime?session_token=allocated"
    monkeypatch.setattr(hf_mod, "AsyncOpenAI", _fake_openai_client(client_kwargs))
    monkeypatch.setattr(hf_mod.httpx, "AsyncClient", _fake_allocator(connect_url, posts))
    monkeypatch.setattr(config, "HF_REALTIME_CONNECTION_MODE", "deployed")
    monkeypatch.setattr(config, "HF_REALTIME_SESSION_URL", "https://lb.example.test/session")
    # A stale local URL must be ignored in deployed mode.
    monkeypatch.setattr(config, "HF_REALTIME_WS_URL", "ws://127.0.0.1:8765/v1/realtime")
    monkeypatch.setattr(config, "HF_TOKEN", hf_token)
    monkeypatch.setattr(hf_mod, "get_token", lambda: cached_token)

    reachy_mini = MagicMock()
    reachy_mini.client.get_status.return_value.hardware_id = hardware_id
    if status_error:
        reachy_mini.client.get_status.side_effect = status_error
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=reachy_mini, movement_manager=MagicMock()))

    client = await handler._build_realtime_client()

    assert client is not None
    assert posts == [("https://lb.example.test/session", expected_header, expected_payload)]
    reachy_mini.client.get_status.assert_called_once_with(wait=False)
    if status_error:
        assert "Daemon status unavailable for realtime session allocation" in caplog.text
    assert client_kwargs["api_key"] == expected_api_key
    assert client_kwargs["base_url"] == "https://hf.example.test/v1"
    assert client_kwargs["websocket_base_url"] == "wss://hf.example.test/v1"
    assert handler._realtime_connect_query == {"session_token": "allocated"}


@pytest.mark.asyncio
async def test_apply_personality_uses_selected_voice_for_lb_allocated_sessions(monkeypatch: Any) -> None:
    """Live personality updates should honor the selected Qwen CustomVoice speaker."""
    monkeypatch.setattr(hf_mod, "get_session_instructions", lambda _instance_path=None: "new instructions")
    monkeypatch.setattr(hf_mod, "get_session_voice", lambda default=HF_DEFAULT_VOICE: "Serena")
    monkeypatch.setattr(config, "HF_REALTIME_SESSION_URL", "https://lb.example.test/session")

    captured_update: dict[str, Any] = {}

    class FakeSession:
        async def update(self, **kwargs: Any) -> None:
            captured_update.update(kwargs)

    class FakeConnection:
        session = FakeSession()

    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))
    handler.connection = FakeConnection()
    monkeypatch.setattr(handler, "_restart_session", AsyncMock(return_value=None))

    result = await handler.apply_personality("mars_rover")

    assert "restarted realtime session" in result.lower()
    session = captured_update["session"]
    assert session["instructions"] == "new instructions"
    assert session["audio"]["output"]["voice"] == "Serena"


@pytest.mark.asyncio
async def test_apply_personality_restores_profile_when_tools_fail(monkeypatch: Any) -> None:
    """A failed tool reload should leave the previous profile selected."""
    selected_profiles: list[str | None] = []

    def select_profile(profile: str | None) -> None:
        selected_profiles.append(profile)
        config.REACHY_MINI_CUSTOM_PROFILE = profile

    def fail_tool_reload(*, force: bool = False) -> None:
        raise RuntimeError("tool reload failed")

    monkeypatch.setattr(config, "REACHY_MINI_CUSTOM_PROFILE", "default")
    monkeypatch.setattr(hf_mod, "set_custom_profile", select_profile)
    monkeypatch.setattr(hf_mod, "get_session_instructions", lambda _instance_path=None: "new instructions")
    monkeypatch.setattr(hf_mod.core_tools, "initialize_tools", fail_tool_reload)
    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))

    result = await handler.apply_personality("broken")

    assert result == "Failed to apply personality: tool reload failed"
    assert config.REACHY_MINI_CUSTOM_PROFILE == "default"
    assert selected_profiles == ["broken", "default"]


@pytest.mark.asyncio
async def test_change_voice_updates_live_hf_session_without_restart(monkeypatch: Any) -> None:
    """Changing Hugging Face voice should update the active session in place."""
    captured_update: dict[str, Any] = {}

    class FakeSession:
        async def update(self, **kwargs: Any) -> None:
            captured_update.update(kwargs)

    class FakeConnection:
        session = FakeSession()

    handler = HuggingFaceRealtimeHandler(ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock()))
    handler.connection = FakeConnection()
    restart = AsyncMock(return_value=None)
    monkeypatch.setattr(handler, "_restart_session", restart)

    result = await handler.change_voice("Serena")

    assert result == "Voice changed to Serena."
    assert handler.get_current_voice() == "Serena"
    restart.assert_not_awaited()
    session = captured_update["session"]
    assert session["audio"]["output"]["voice"] == "Serena"
