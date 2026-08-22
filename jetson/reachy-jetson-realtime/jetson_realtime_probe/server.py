"""Minimal OpenAI-compatible realtime websocket probe backed by Ollama."""

import os
import json
import uuid
import wave
import base64
import asyncio
import audioop
import logging
from io import BytesIO
from typing import Any
from pathlib import Path

import httpx
from websockets.legacy.server import WebSocketServerProtocol, serve


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3:4b"
DEFAULT_OLLAMA_TIMEOUT_S = 180.0
DEFAULT_OLLAMA_NUM_PREDICT = 64
DEFAULT_TTS_PROVIDER = "none"
DEFAULT_QWEN_TTS_URL = "http://192.168.0.150:8000/v1/audio/speech"
DEFAULT_QWEN_TTS_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
DEFAULT_QWEN_TTS_VOICE = "Aiden"
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1

logger = logging.getLogger("jetson_realtime_probe")


def load_env_file(path: str = ".env") -> None:
    """Load simple KEY=VALUE settings without adding a runtime dependency."""
    env_path = os.path.abspath(path)
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


load_env_file()


def event_id(prefix: str) -> str:
    """Return a unique realtime event id."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def ollama_model() -> str:
    """Return the configured Ollama model name."""
    return os.getenv("JETSON_REALTIME_OLLAMA_MODEL", DEFAULT_MODEL)


def ollama_base_url() -> str:
    """Return the configured Ollama base URL."""
    return os.getenv("JETSON_REALTIME_OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")


def ollama_timeout_s() -> float:
    """Return the configured Ollama request timeout."""
    return _env_float("JETSON_REALTIME_OLLAMA_TIMEOUT_S", DEFAULT_OLLAMA_TIMEOUT_S)


def ollama_num_predict() -> int:
    """Return the configured short-response generation cap."""
    return _env_int("JETSON_REALTIME_OLLAMA_NUM_PREDICT", DEFAULT_OLLAMA_NUM_PREDICT)


def ollama_think_enabled() -> bool:
    """Return whether Ollama thinking mode should be enabled."""
    value = os.getenv("JETSON_REALTIME_OLLAMA_THINK", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


async def ask_ollama(prompt: str, *, model: str | None = None, base_url: str | None = None) -> str:
    """Ask configured Ollama for one short response."""
    selected_model = model or ollama_model()
    ollama_url = (base_url or ollama_base_url()).rstrip("/")
    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": "You are a concise Reachy Mini realtime endpoint smoke test."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": ollama_think_enabled(),
        "options": {"temperature": 0.2, "num_predict": ollama_num_predict()},
    }
    async with httpx.AsyncClient(timeout=ollama_timeout_s()) as client:
        response = await client.post(f"{ollama_url}/api/chat", json=payload)
        response.raise_for_status()
    data = response.json()
    message = data.get("message") if isinstance(data, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if content:
        return str(content).strip()
    thinking = message.get("thinking") if isinstance(message, dict) else None
    if thinking:
        return "[thinking-only response] " + str(thinking).strip()
    return ""


def tts_provider() -> str:
    """Return the configured TTS provider name."""
    return os.getenv("JETSON_REALTIME_TTS_PROVIDER", DEFAULT_TTS_PROVIDER).strip().lower()


def qwen_tts_url() -> str:
    """Return the configured Qwen3-TTS HTTP endpoint."""
    return os.getenv("JETSON_REALTIME_QWEN_TTS_URL", DEFAULT_QWEN_TTS_URL).strip()


def qwen_tts_model() -> str:
    """Return the configured Qwen3-TTS model id."""
    return os.getenv("JETSON_REALTIME_QWEN_TTS_MODEL", DEFAULT_QWEN_TTS_MODEL).strip()


def qwen_tts_voice() -> str:
    """Return the configured Qwen3-TTS voice."""
    return os.getenv("JETSON_REALTIME_QWEN_TTS_VOICE", DEFAULT_QWEN_TTS_VOICE).strip()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer value for %s=%r, using %s", name, value, default)
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid float value for %s=%r, using %s", name, value, default)
        return default


def _read_wav_as_16khz_mono_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        pcm = wav_file.readframes(wav_file.getnframes())

    if sample_width != SAMPLE_WIDTH:
        pcm = audioop.lin2lin(pcm, sample_width, SAMPLE_WIDTH)
    if channels > 1:
        pcm = audioop.tomono(pcm, SAMPLE_WIDTH, 0.5, 0.5)
    if sample_rate != SAMPLE_RATE:
        pcm, _ = audioop.ratecv(pcm, SAMPLE_WIDTH, CHANNELS, sample_rate, SAMPLE_RATE, None)
    return bytes(pcm)


def _read_wav_bytes_as_16khz_mono_pcm(wav_bytes: bytes) -> bytes:
    with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        pcm = wav_file.readframes(wav_file.getnframes())

    if sample_width != SAMPLE_WIDTH:
        pcm = audioop.lin2lin(pcm, sample_width, SAMPLE_WIDTH)
    if channels > 1:
        pcm = audioop.tomono(pcm, SAMPLE_WIDTH, 0.5, 0.5)
    if sample_rate != SAMPLE_RATE:
        pcm, _ = audioop.ratecv(pcm, SAMPLE_WIDTH, CHANNELS, sample_rate, SAMPLE_RATE, None)
    return bytes(pcm)


def _chunk_pcm(pcm: bytes, chunk_ms: int = 100) -> list[bytes]:
    bytes_per_ms = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS // 1000
    chunk_size = max(bytes_per_ms * chunk_ms, SAMPLE_WIDTH)
    return [pcm[index : index + chunk_size] for index in range(0, len(pcm), chunk_size)]


async def _qwen3_tts_http(text: str, voice: str) -> bytes:
    payload = {
        "model": qwen_tts_model(),
        "input": text,
        "voice": voice,
        "response_format": "wav",
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(qwen_tts_url(), json=payload)
        response.raise_for_status()
        audio_bytes = response.content

    return _read_wav_bytes_as_16khz_mono_pcm(audio_bytes)


async def synthesize_speech(text: str, *, voice: str | None = None) -> bytes:
    """Return 16 kHz mono int16 PCM for assistant speech, if configured."""
    provider = tts_provider()
    if not text.strip() or provider in {"", "none"}:
        return b""
    if provider == "qwen3tts_http":
        return await _qwen3_tts_http(text, voice or qwen_tts_voice())
    raise RuntimeError(f"Unsupported TTS provider: {provider}")


async def _send(websocket: WebSocketServerProtocol, payload: dict[str, Any]) -> None:
    await websocket.send(json.dumps(payload))


async def handle_connection(websocket: WebSocketServerProtocol) -> None:
    """Handle the subset of realtime events needed for a first Reachy probe."""
    last_user_text = "Say a tiny hello from the Jetson."
    await _send(
        websocket,
        {
            "type": "session.created",
            "event_id": event_id("evt"),
            "session": {"type": "realtime"},
        },
    )

    async for raw_message in websocket:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            await _send(
                websocket, {"type": "error", "event_id": event_id("evt"), "error": {"message": "invalid json"}}
            )
            continue

        event_type = payload.get("type")
        if event_type == "session.update":
            await _send(
                websocket,
                {
                    "type": "session.updated",
                    "event_id": event_id("evt"),
                    "session": payload.get("session") or {"type": "realtime"},
                },
            )
            continue

        if event_type == "conversation.item.create":
            item = payload.get("item") or {}
            content_items = item.get("content") if isinstance(item, dict) else None
            if isinstance(content_items, list):
                text_parts = []
                for part in content_items:
                    if isinstance(part, dict):
                        text_parts.append(str(part.get("text") or part.get("transcript") or ""))
                candidate = " ".join(part for part in text_parts if part).strip()
                if candidate:
                    last_user_text = candidate
            continue

        if event_type == "input_audio_buffer.append":
            audio = str(payload.get("audio") or "")
            if audio:
                try:
                    base64.b64decode(audio)
                except Exception:
                    await _send(
                        websocket,
                        {
                            "type": "error",
                            "event_id": event_id("evt"),
                            "error": {"message": "invalid input audio base64"},
                        },
                    )
            continue

        if event_type == "response.create":
            response_id = event_id("resp")
            await _send(
                websocket,
                {
                    "type": "response.created",
                    "event_id": event_id("evt"),
                    "response": {"id": response_id, "object": "realtime.response", "status": "in_progress"},
                },
            )
            try:
                answer = await ask_ollama(last_user_text)
            except Exception as exc:
                await _send(
                    websocket,
                    {
                        "type": "error",
                        "event_id": event_id("evt"),
                        "error": {"message": f"ollama failed: {type(exc).__name__}: {exc}"},
                    },
                )
                answer = "Ollama failed during the Jetson realtime probe."
            item_id = event_id("msg")
            await _send(
                websocket,
                {
                    "type": "response.output_audio_transcript.done",
                    "event_id": event_id("evt"),
                    "response_id": response_id,
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "transcript": answer,
                },
            )
            await _send(
                websocket,
                {
                    "type": "response.output_text.done",
                    "event_id": event_id("evt"),
                    "response_id": response_id,
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": answer,
                },
            )
            try:
                speech_pcm = await synthesize_speech(answer)
            except Exception as exc:
                await _send(
                    websocket,
                    {
                        "type": "error",
                        "event_id": event_id("evt"),
                        "error": {"message": f"tts failed: {type(exc).__name__}: {exc}"},
                    },
                )
                speech_pcm = b""
            for chunk in _chunk_pcm(speech_pcm):
                await _send(
                    websocket,
                    {
                        "type": "response.output_audio.delta",
                        "event_id": event_id("evt"),
                        "response_id": response_id,
                        "item_id": item_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": base64.b64encode(chunk).decode("ascii"),
                    },
                )
            if speech_pcm:
                await _send(
                    websocket,
                    {
                        "type": "response.output_audio.done",
                        "event_id": event_id("evt"),
                        "response_id": response_id,
                        "item_id": item_id,
                        "output_index": 0,
                        "content_index": 0,
                    },
                )
            await _send(
                websocket,
                {
                    "type": "response.done",
                    "event_id": event_id("evt"),
                    "response": {"id": response_id, "object": "realtime.response", "status": "completed"},
                },
            )
            continue

        if event_type == "response.cancel":
            await _send(
                websocket,
                {
                    "type": "response.done",
                    "event_id": event_id("evt"),
                    "response": {"id": event_id("resp"), "object": "realtime.response", "status": "cancelled"},
                },
            )


async def run_server() -> None:
    """Run the Jetson realtime probe websocket."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s:%(lineno)d | %(message)s")
    host = os.getenv("JETSON_REALTIME_HOST", DEFAULT_HOST)
    port = _env_int("JETSON_REALTIME_PORT", DEFAULT_PORT)
    ping_interval = _env_float("JETSON_REALTIME_WS_PING_INTERVAL_S", 60.0)
    ping_timeout = _env_float("JETSON_REALTIME_WS_PING_TIMEOUT_S", 60.0)
    async with serve(handle_connection, host, port, ping_interval=ping_interval, ping_timeout=ping_timeout):
        logger.info("Listening on ws://%s:%s/v1/realtime", host, port)
        await asyncio.Future()


def main() -> None:
    """Run the Jetson realtime probe."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
