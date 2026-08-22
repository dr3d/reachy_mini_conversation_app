import os
import wave
from pathlib import Path

import httpx
import pytest
from jetson_realtime_probe import server


def _write_wav(path: Path, pcm: bytes, sample_rate: int = 24000) -> None:
    """Write a mono 16-bit WAV fixture."""
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)


def test_read_wav_as_16khz_mono_pcm_resamples(tmp_path: Path) -> None:
    """Qwen WAV responses should become 16 kHz mono PCM."""
    wav_path = tmp_path / "speech.wav"
    _write_wav(wav_path, b"\x00\x01" * 2400, sample_rate=24000)

    pcm = server._read_wav_as_16khz_mono_pcm(wav_path)

    assert pcm
    assert len(pcm) % 2 == 0
    assert len(pcm) < 4800


@pytest.mark.asyncio
async def test_qwen3_tts_http_posts_openai_style_payload(monkeypatch, tmp_path: Path) -> None:
    """The Jetson probe should call the RTX Qwen3-TTS server contract."""
    captured: dict[str, object] = {}
    wav_path = tmp_path / "speech.wav"
    _write_wav(wav_path, b"\x00\x01" * 1600, sample_rate=16000)
    wav_bytes = wav_path.read_bytes()

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
            captured["url"] = url
            captured["payload"] = json
            return httpx.Response(200, content=wav_bytes, request=httpx.Request("POST", url))

    monkeypatch.setattr(server.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setitem(os.environ, "JETSON_REALTIME_QWEN_TTS_URL", "http://tts.test/v1/audio/speech")
    monkeypatch.setitem(os.environ, "JETSON_REALTIME_QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")

    pcm = await server._qwen3_tts_http("hello", "Aiden")

    assert pcm
    assert captured["url"] == "http://tts.test/v1/audio/speech"
    assert captured["payload"] == {
        "model": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        "input": "hello",
        "voice": "Aiden",
        "response_format": "wav",
    }
