import json
import base64
import asyncio

import pytest
import websockets
from jetson_realtime_probe import server


@pytest.mark.asyncio
async def test_realtime_websocket_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """The probe should emit the realtime events the app expects."""

    async def fake_ask_ollama(_prompt: str, **_kwargs: object) -> str:
        return "two words"

    monkeypatch.setattr(server, "ask_ollama", fake_ask_ollama)

    async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        async with websockets.connect(f"ws://127.0.0.1:{port}/v1/realtime") as ws:
            created = json.loads(await ws.recv())
            assert created["type"] == "session.created"

            await ws.send(json.dumps({"type": "session.update", "session": {"type": "realtime"}}))
            updated = json.loads(await ws.recv())
            assert updated["type"] == "session.updated"

            await ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Reply with two words."}],
                        },
                    }
                )
            )
            await ws.send(json.dumps({"type": "response.create"}))

            seen = []
            for _ in range(6):
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=70.0))
                seen.append(event["type"])
                if event["type"] == "response.done":
                    break

    assert "response.created" in seen
    assert "response.output_audio_transcript.done" in seen
    assert "response.done" in seen


@pytest.mark.asyncio
async def test_realtime_websocket_streams_audio_when_tts_returns_pcm(monkeypatch) -> None:
    """Configured TTS PCM should be streamed as realtime audio deltas."""

    async def fake_ask_ollama(_prompt: str, **_kwargs: object) -> str:
        return "spoken text"

    async def fake_synthesize_speech(_text: str, **_kwargs: object) -> bytes:
        return b"\x01\x02" * 2000

    monkeypatch.setattr(server, "ask_ollama", fake_ask_ollama)
    monkeypatch.setattr(server, "synthesize_speech", fake_synthesize_speech)

    async with websockets.serve(server.handle_connection, "127.0.0.1", 0) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        async with websockets.connect(f"ws://127.0.0.1:{port}/v1/realtime") as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "response.create"}))

            events = []
            for _ in range(8):
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
                events.append(event)
                if event["type"] == "response.done":
                    break

    event_types = [event["type"] for event in events]
    audio_delta = next(event for event in events if event["type"] == "response.output_audio.delta")

    assert "response.output_audio.delta" in event_types
    assert "response.output_audio.done" in event_types
    assert base64.b64decode(audio_delta["delta"])
