"""LM Studio-backed OpenAI Realtime bridge for local Reachy voice experiments."""

import os
import re
import json
import uuid
import wave
import base64
import asyncio
import audioop
import logging
import platform
import tempfile
import subprocess
from typing import Any, Protocol
from pathlib import Path
from dataclasses import field, dataclass

import httpx
import websockets
from dotenv import load_dotenv
from websockets.server import WebSocketServerProtocol


SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

logger = logging.getLogger("local_voice_bridge")

load_dotenv(Path(__file__).with_name(".env"))

_FALSE_VALUES = {"0", "false", "no", "off"}

_EMOJI_EMOTION_BY_CODEPOINT: dict[int, str] = {
    0x2600: "happy",
    0x26A1: "electric",
    0x2705: "success",
    0x2728: "amazed",
    0x274C: "no_firm",
    0x2764: "loving",
    0x1F44B: "greeting",
    0x1F44D: "yes_understanding",
    0x1F44E: "no_firm",
    0x1F44F: "success",
    0x1F47B: "surprised",
    0x1F4A1: "thinking",
    0x1F4A4: "sleepy",
    0x1F4AF: "success",
    0x1F525: "excited",
    0x1F600: "happy",
    0x1F601: "happy",
    0x1F602: "happy",
    0x1F603: "happy",
    0x1F604: "happy",
    0x1F605: "embarrassed",
    0x1F606: "happy",
    0x1F609: "happy",
    0x1F60A: "happy",
    0x1F60D: "loving",
    0x1F612: "displeased",
    0x1F614: "sad",
    0x1F615: "confused",
    0x1F616: "displeased",
    0x1F618: "loving",
    0x1F61E: "sad",
    0x1F620: "angry",
    0x1F621: "angry",
    0x1F622: "sad",
    0x1F62D: "sad",
    0x1F62E: "surprised",
    0x1F631: "scared",
    0x1F632: "surprised",
    0x1F634: "sleepy",
    0x1F635: "confused",
    0x1F641: "sad",
    0x1F642: "happy",
    0x1F643: "confused",
    0x1F914: "thinking",
    0x1F917: "welcoming",
    0x1F923: "happy",
    0x1F929: "amazed",
    0x1F92C: "angry",
    0x1F92F: "surprised",
    0x1F970: "loving",
    0x1F973: "success",
    0x1F97A: "sad",
    0x1F9D0: "thinking",
    0x1FAE1: "yes_understanding",
}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() not in _FALSE_VALUES


def _event_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now_item_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _b64_pcm(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode("ascii")


def _pcm_from_b64(value: str) -> bytes:
    return base64.b64decode(value)


def _write_wav(path: Path, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)


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
    return pcm


def _rms(pcm: bytes) -> int:
    if not pcm:
        return 0
    return audioop.rms(pcm, SAMPLE_WIDTH)


def _chunk_pcm(pcm: bytes, chunk_ms: int = 100) -> list[bytes]:
    bytes_per_ms = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS // 1000
    chunk_size = max(bytes_per_ms * chunk_ms, SAMPLE_WIDTH)
    return [pcm[index : index + chunk_size] for index in range(0, len(pcm), chunk_size)]


def _decode_escaped_text(text: str) -> str:
    decoded = text
    decoded = re.sub(r"(?:\\)+n", " ", decoded)
    decoded = re.sub(r"(?:\\)+r", " ", decoded)
    decoded = re.sub(r"(?:\\)+t", " ", decoded)
    decoded = re.sub(
        r"(?:\\)+u([dD][89a-bA-B][0-9a-fA-F]{2})(?:\\)+u([dD][c-fC-F][0-9a-fA-F]{2})",
        lambda match: chr(0x10000 + ((int(match.group(1), 16) - 0xD800) << 10) + (int(match.group(2), 16) - 0xDC00)),
        decoded,
    )
    decoded = re.sub(
        r"(?:\\)+u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        decoded,
    )
    decoded = re.sub(
        r"(?:\\)+U([0-9a-fA-F]{8})",
        lambda match: chr(int(match.group(1), 16)),
        decoded,
    )
    return decoded


def _is_emoji_component(codepoint: int) -> bool:
    return (
        codepoint == 0x200D
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0x1F1E6 <= codepoint <= 0x1F1FF
        or 0x1F3FB <= codepoint <= 0x1F3FF
        or 0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
    )


def _speech_text_and_emoji_emotion(text: str) -> tuple[str, str | None]:
    decoded = _decode_escaped_text(text)
    emotion: str | None = None
    speech_chars = []
    for char in decoded:
        codepoint = ord(char)
        if emotion is None:
            emotion = _EMOJI_EMOTION_BY_CODEPOINT.get(codepoint)
        if _is_emoji_component(codepoint):
            continue
        speech_chars.append(char)

    decoded = "".join(speech_chars)
    decoded = re.sub(r"(\d+(?:\.\d+)?)\s*(?:\u00b0|℃)\s*[Cc]\b", r"\1 degrees Celsius", decoded)
    decoded = re.sub(r"(\d+(?:\.\d+)?)\s*(?:\u00b0|℉)\s*[Ff]\b", r"\1 degrees Fahrenheit", decoded)
    decoded = decoded.replace("\u00b0", " degrees ")
    decoded = decoded.replace("\u2026", ".")
    decoded = re.sub(r"\.{3,}", ".", decoded)
    decoded = decoded.replace("\u2014", ", ")
    decoded = decoded.replace("\u2013", ", ")
    decoded = decoded.replace("\u2212", " minus ")
    decoded = re.sub(r"\\(?=[^\w\s])", "", decoded)
    decoded = re.sub(r"\s+", " ", decoded)
    decoded = re.sub(r"\s+,", ",", decoded)
    decoded = re.sub(r"\s+\.", ".", decoded)
    decoded = re.sub(r"([.!?])\s*\.", r"\1", decoded)
    return decoded.strip(), emotion


def _speech_text(text: str) -> str:
    return _speech_text_and_emoji_emotion(text)[0]


class _SttProvider(Protocol):
    async def transcribe(self, pcm: bytes) -> str: ...


class _TtsProvider(Protocol):
    async def synthesize(self, text: str) -> bytes: ...


class _CommandStt:
    def __init__(self, command_template: str) -> None:
        self.command_template = command_template

    async def transcribe(self, pcm: bytes) -> str:
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "input.wav"
            _write_wav(wav_path, pcm)
            command = self.command_template.format(wav=str(wav_path))
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    command,
                    shell=True,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                details = (exc.stderr or exc.stdout or str(exc)).strip()
                raise RuntimeError(f"STT command failed: {details}") from exc
        return result.stdout.strip()


class _MissingStt:
    async def transcribe(self, pcm: bytes) -> str:
        raise RuntimeError("LOCAL_BRIDGE_STT_COMMAND is required for microphone turns.")


class _CommandTts:
    def __init__(self, command_template: str) -> None:
        self.command_template = command_template

    async def synthesize(self, text: str) -> bytes:
        text = _speech_text(text)
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "output.wav"
            command = self.command_template.format(
                text=text,
                wav=str(wav_path),
            )
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    command,
                    shell=True,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                details = (exc.stderr or exc.stdout or str(exc)).strip()
                raise RuntimeError(f"TTS command failed: {details}") from exc
            return _read_wav_as_16khz_mono_pcm(wav_path)


class _WindowsSapiTts:
    async def synthesize(self, text: str) -> bytes:
        text = _speech_text(text)
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "output.wav"
            script_path = Path(tmp_dir) / "speak.ps1"
            script_path.write_text(
                "\n".join(
                    [
                        "param([string]$OutputPath, [string]$Text)",
                        "Add-Type -AssemblyName System.Speech",
                        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
                        "try {",
                        "    $s.SetOutputToWaveFile($OutputPath)",
                        "    $s.Speak($Text)",
                        "} finally {",
                        "    $s.Dispose()",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(script_path),
                        str(wav_path),
                        text,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                details = (exc.stderr or exc.stdout or str(exc)).strip()
                raise RuntimeError(f"Windows SAPI TTS failed: {details}") from exc
            return _read_wav_as_16khz_mono_pcm(wav_path)


class _PiperTts:
    def __init__(self) -> None:
        bridge_dir = Path(__file__).parent
        self.exe_path = Path(_env("LOCAL_BRIDGE_PIPER_EXE", str(bridge_dir / "piper" / "piper" / "piper.exe")))
        self.model_path = Path(
            _env("LOCAL_BRIDGE_PIPER_MODEL", str(bridge_dir / "piper" / "voices" / "en_US-lessac-high.onnx"))
        )
        config = _env("LOCAL_BRIDGE_PIPER_CONFIG")
        self.config_path = Path(config) if config else self.model_path.with_suffix(f"{self.model_path.suffix}.json")
        self.speaker = _env("LOCAL_BRIDGE_PIPER_SPEAKER")

    async def synthesize(self, text: str) -> bytes:
        text = _speech_text(text)
        if not self.exe_path.exists():
            raise RuntimeError(f"Piper executable not found: {self.exe_path}")
        if not self.model_path.exists():
            raise RuntimeError(f"Piper model not found: {self.model_path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "output.wav"
            command = [
                str(self.exe_path),
                "--model",
                str(self.model_path),
                "--output_file",
                str(wav_path),
            ]
            if self.config_path.exists():
                command.extend(["--config", str(self.config_path)])
            if self.speaker:
                command.extend(["--speaker", self.speaker])

            try:
                await asyncio.to_thread(
                    subprocess.run,
                    command,
                    input=text,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                details = (exc.stderr or exc.stdout or str(exc)).strip()
                raise RuntimeError(f"Piper TTS failed: {details}") from exc
            return _read_wav_as_16khz_mono_pcm(wav_path)


class _MissingTts:
    async def synthesize(self, text: str) -> bytes:
        raise RuntimeError("No TTS provider configured. Set LOCAL_BRIDGE_TTS_COMMAND.")


@dataclass
class _LlmResult:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class _LlmProvider(Protocol):
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> _LlmResult: ...


class _LmStudioProvider:
    def __init__(self) -> None:
        self.base_url = _env("LOCAL_BRIDGE_LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
        self.model = _env("LOCAL_BRIDGE_LMSTUDIO_MODEL")

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> _LlmResult:
        if not self.model:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/models")
                response.raise_for_status()
                models = response.json().get("data") or []
                if not models:
                    raise RuntimeError("LM Studio has no loaded models.")
                self.model = str(models[0]["id"])

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": float(_env("LOCAL_BRIDGE_TEMPERATURE", "0.7")),
            "stream": False,
        }
        chat_tools = _to_chat_completion_tools(tools)
        if chat_tools:
            payload["tools"] = chat_tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"LM Studio chat failed: {response.text[:2000]}") from exc
            data = response.json()

        message = data["choices"][0]["message"]
        return _LlmResult(
            content=message.get("content") or "",
            tool_calls=message.get("tool_calls") or [],
        )


def _to_chat_completion_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chat_tools: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = tool.get("function")
        if isinstance(function, dict):
            chat_tools.append({"type": "function", "function": function})
            continue

        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        chat_tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description") or "",
                    "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return chat_tools


def _tool_available(tools: list[dict[str, Any]], name: str) -> bool:
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = tool.get("function")
        if isinstance(function, dict) and function.get("name") == name:
            return True
        if tool.get("name") == name:
            return True
    return False


def _emotion_tool_call(emotion: str) -> dict[str, Any]:
    return {
        "id": _event_id("call"),
        "type": "function",
        "function": {
            "name": "play_emotion",
            "arguments": json.dumps({"emotion": emotion}),
        },
    }


@dataclass
class _BridgeSession:
    websocket: WebSocketServerProtocol
    llm: _LlmProvider
    stt: _SttProvider
    tts: _TtsProvider
    instructions: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    audio_buffer: bytearray = field(default_factory=bytearray)
    speech_buffer: bytearray = field(default_factory=bytearray)
    speaking: bool = False
    silence_ms: int = 0
    speech_item_id: str | None = None
    response_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, payload: dict[str, Any]) -> None:
        await self.websocket.send(json.dumps(payload))

    async def error(self, message: str, code: str = "local_bridge_error") -> None:
        logger.warning("%s: %s", code, message)
        await self.send(
            {
                "type": "error",
                "event_id": _event_id("evt"),
                "error": {"type": "server_error", "code": code, "message": message},
            }
        )

    async def update_session(self, payload: dict[str, Any]) -> None:
        session = payload.get("session") or {}
        if isinstance(session, dict):
            self.instructions = str(session.get("instructions") or self.instructions)
            tools = session.get("tools")
            if isinstance(tools, list):
                self.tools = tools
        self.messages = [{"role": "system", "content": self.instructions}] if self.instructions else []
        await self.send({"type": "session.updated", "event_id": _event_id("evt"), "session": session})

    async def create_item(self, payload: dict[str, Any]) -> None:
        item = payload.get("item") or {}
        if not isinstance(item, dict):
            await self.error("conversation.item.create item must be an object.", "invalid_item")
            return

        item_type = item.get("type")
        if item_type == "message" and item.get("role") == "user":
            content = self._content_from_user_item(item)
            if content:
                self.messages.append({"role": "user", "content": content})
        elif item_type == "function_call_output":
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.get("call_id"),
                    "content": item.get("output") or "",
                }
            )

        await self.send(
            {
                "type": "conversation.item.created",
                "event_id": _event_id("evt"),
                "previous_item_id": None,
                "item": {**item, "id": item.get("id") or _now_item_id("item")},
            }
        )

    def _content_from_user_item(self, item: dict[str, Any]) -> str | list[dict[str, Any]]:
        message_parts: list[dict[str, Any]] = []
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            content_type = content.get("type")
            if content_type == "input_text":
                text = str(content.get("text") or "").strip()
                if text:
                    message_parts.append({"type": "text", "text": text})
            elif content_type == "input_image":
                image_url = content.get("image_url")
                if isinstance(image_url, str) and image_url:
                    message_parts.append({"type": "image_url", "image_url": {"url": image_url}})

        if not message_parts:
            return ""
        if len(message_parts) == 1 and message_parts[0]["type"] == "text":
            return str(message_parts[0]["text"])
        return message_parts

    async def append_audio(self, payload: dict[str, Any]) -> None:
        audio = payload.get("audio")
        if not isinstance(audio, str) or not audio:
            return
        pcm = _pcm_from_b64(audio)
        self.audio_buffer.extend(pcm)
        await self._vad_step(pcm)

    async def _vad_step(self, pcm: bytes) -> None:
        speech_threshold = int(_env("LOCAL_BRIDGE_VAD_RMS", "350"))
        stop_silence_ms = int(_env("LOCAL_BRIDGE_VAD_STOP_MS", "700"))
        frame_ms = max(1, int(len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS) * 1000))
        is_speech = _rms(pcm) >= speech_threshold

        if is_speech:
            if not self.speaking:
                self.speaking = True
                self.silence_ms = 0
                self.speech_buffer.clear()
                self.speech_item_id = _now_item_id("item")
                await self.send(
                    {
                        "type": "input_audio_buffer.speech_started",
                        "event_id": _event_id("evt"),
                        "item_id": self.speech_item_id,
                        "audio_start_ms": max(0, len(self.audio_buffer) // (SAMPLE_RATE * SAMPLE_WIDTH) * 1000),
                    }
                )
            self.speech_buffer.extend(pcm)
            self.silence_ms = 0
            return

        if self.speaking:
            self.speech_buffer.extend(pcm)
            self.silence_ms += frame_ms
            if self.silence_ms >= stop_silence_ms:
                await self._finish_speech_turn()

    async def _finish_speech_turn(self) -> None:
        item_id = self.speech_item_id or _now_item_id("item")
        self.speaking = False
        self.silence_ms = 0
        speech_pcm = bytes(self.speech_buffer)
        self.speech_buffer.clear()
        await self.send(
            {
                "type": "input_audio_buffer.speech_stopped",
                "event_id": _event_id("evt"),
                "item_id": item_id,
                "audio_end_ms": len(self.audio_buffer) // (SAMPLE_RATE * SAMPLE_WIDTH) * 1000,
            }
        )
        try:
            transcript = await self.stt.transcribe(speech_pcm)
        except Exception as exc:
            await self.error(str(exc), "stt_failed")
            return

        transcript = transcript.strip()
        if not transcript:
            return

        self.messages.append({"role": "user", "content": transcript})
        await self.send(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "event_id": _event_id("evt"),
                "item_id": item_id,
                "content_index": 0,
                "transcript": transcript,
            }
        )
        await self.respond()

    async def respond(self) -> None:
        async with self.response_lock:
            response_id = _now_item_id("resp")
            item_id = _now_item_id("item")
            await self.send(
                {
                    "type": "response.created",
                    "event_id": _event_id("evt"),
                    "response": {"id": response_id, "object": "realtime.response", "status": "in_progress"},
                }
            )

            try:
                result = await self.llm.chat(self.messages, self.tools)
            except Exception as exc:
                await self.error(str(exc), "llm_failed")
                await self._response_done(response_id, "failed")
                return

            if result.tool_calls:
                assistant_message = {
                    "role": "assistant",
                    "content": result.content or None,
                    "tool_calls": result.tool_calls,
                }
                self.messages.append(assistant_message)
                for tool_call in result.tool_calls:
                    function = tool_call.get("function") or {}
                    await self.send(
                        {
                            "type": "response.function_call_arguments.done",
                            "event_id": _event_id("evt"),
                            "response_id": response_id,
                            "item_id": _now_item_id("fc"),
                            "output_index": 0,
                            "call_id": tool_call.get("id") or _event_id("call"),
                            "name": function.get("name"),
                            "arguments": function.get("arguments") or "{}",
                        }
                    )
                await self._response_done(response_id, "completed")
                return

            text, emoji_emotion = _speech_text_and_emoji_emotion(result.content.strip())
            emoji_tool_call = None
            if (
                emoji_emotion
                and _env_bool("LOCAL_BRIDGE_EMOJI_EMOTIONS", True)
                and _tool_available(self.tools, "play_emotion")
            ):
                emoji_tool_call = _emotion_tool_call(emoji_emotion)

            if text or emoji_tool_call:
                assistant_message: dict[str, Any] = {"role": "assistant", "content": text or None}
                if emoji_tool_call:
                    assistant_message["tool_calls"] = [emoji_tool_call]
                self.messages.append(assistant_message)

            if emoji_tool_call:
                function = emoji_tool_call["function"]
                await self.send(
                    {
                        "type": "response.function_call_arguments.done",
                        "event_id": _event_id("evt"),
                        "response_id": response_id,
                        "item_id": _now_item_id("fc"),
                        "output_index": 0,
                        "call_id": emoji_tool_call["id"],
                        "name": function["name"],
                        "arguments": function["arguments"],
                    }
                )

            if text:
                await self.send(
                    {
                        "type": "response.output_audio_transcript.done",
                        "event_id": _event_id("evt"),
                        "response_id": response_id,
                        "item_id": item_id,
                        "output_index": 0,
                        "content_index": 0,
                        "transcript": text,
                    }
                )
                try:
                    audio_pcm = await self.tts.synthesize(text)
                except Exception as exc:
                    await self.error(str(exc), "tts_failed")
                    audio_pcm = b""
                for chunk in _chunk_pcm(audio_pcm):
                    await self.send(
                        {
                            "type": "response.output_audio.delta",
                            "event_id": _event_id("evt"),
                            "response_id": response_id,
                            "item_id": item_id,
                            "output_index": 0,
                            "content_index": 0,
                            "delta": _b64_pcm(chunk),
                        }
                    )

            await self.send(
                {
                    "type": "response.output_audio.done",
                    "event_id": _event_id("evt"),
                    "response_id": response_id,
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                }
            )
            await self._response_done(response_id, "completed")

    async def _response_done(self, response_id: str, status: str) -> None:
        await self.send(
            {
                "type": "response.done",
                "event_id": _event_id("evt"),
                "response": {"id": response_id, "object": "realtime.response", "status": status},
            }
        )


def _build_llm_provider() -> _LlmProvider:
    provider = _env("LOCAL_BRIDGE_LLM_PROVIDER", "lmstudio").lower()
    if provider == "lmstudio":
        return _LmStudioProvider()
    raise RuntimeError("Only LOCAL_BRIDGE_LLM_PROVIDER=lmstudio is supported.")


def _build_stt_provider() -> _SttProvider:
    command = _env("LOCAL_BRIDGE_STT_COMMAND")
    if command:
        return _CommandStt(command)
    return _MissingStt()


def _build_tts_provider() -> _TtsProvider:
    provider = _env("LOCAL_BRIDGE_TTS_PROVIDER", "").lower()
    if provider == "piper":
        return _PiperTts()
    if provider and provider != "sapi":
        raise RuntimeError("LOCAL_BRIDGE_TTS_PROVIDER must be piper or sapi.")

    command = _env("LOCAL_BRIDGE_TTS_COMMAND")
    if command:
        return _CommandTts(command)
    if platform.system() == "Windows":
        return _WindowsSapiTts()
    return _MissingTts()


async def _handle_connection(websocket: WebSocketServerProtocol) -> None:
    session = _BridgeSession(
        websocket=websocket,
        llm=_build_llm_provider(),
        stt=_build_stt_provider(),
        tts=_build_tts_provider(),
    )
    await session.send(
        {
            "type": "session.created",
            "event_id": _event_id("evt"),
            "session": {"type": "realtime"},
        }
    )
    async for raw_message in websocket:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            await session.error("Invalid JSON websocket message.", "invalid_json")
            continue

        event_type = payload.get("type")
        logger.debug("client event: %s", event_type)
        if event_type == "session.update":
            await session.update_session(payload)
        elif event_type == "conversation.item.create":
            await session.create_item(payload)
        elif event_type == "input_audio_buffer.append":
            await session.append_audio(payload)
        elif event_type == "input_audio_buffer.clear":
            session.audio_buffer.clear()
            session.speech_buffer.clear()
            await session.send({"type": "input_audio_buffer.cleared", "event_id": _event_id("evt")})
        elif event_type == "response.create":
            await session.respond()
        elif event_type == "response.cancel":
            await session._response_done(_now_item_id("resp"), "cancelled")
        else:
            logger.debug("Ignoring unsupported client event: %s", event_type)


async def main() -> None:
    """Run the local websocket bridge."""
    logging.basicConfig(
        level=getattr(logging, _env("LOCAL_BRIDGE_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s:%(lineno)d | %(message)s",
    )
    host = _env("LOCAL_BRIDGE_HOST", DEFAULT_HOST)
    port = int(_env("LOCAL_BRIDGE_PORT", str(DEFAULT_PORT)))
    logger.info("Starting local voice bridge on ws://%s:%s/v1/realtime", host, port)
    async with websockets.serve(_handle_connection, host, port):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
