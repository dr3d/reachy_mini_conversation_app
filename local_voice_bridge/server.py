"""LM Studio-backed OpenAI Realtime bridge for local Reachy voice experiments."""

import os
import re
import json
import time
import uuid
import wave
import base64
import asyncio
import audioop
import logging
import platform
import tempfile
import importlib
import subprocess
from io import BytesIO
from typing import Any, Protocol
from pathlib import Path
from dataclasses import field, dataclass

import httpx
from dotenv import load_dotenv
from websockets.legacy.server import WebSocketServerProtocol, serve


SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

logger = logging.getLogger("local_voice_bridge")

load_dotenv(Path(__file__).with_name(".env"), override=True)

_FALSE_VALUES = {"0", "false", "no", "off"}
_DLL_DIRECTORY_HANDLES: list[object] = []
_MARKDOWN_BULLET_RE = re.compile(r"(?m)^\s*[*+-]\s+")
_MARKDOWN_EMPHASIS_RE = re.compile(r"(?<!\\)\*{1,3}([^*\n]+?)(?<!\\)\*{1,3}")

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


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer value for %s=%r, using %s", name, value, default)
        return default


def _env_float(name: str, default: float) -> float:
    value = _env(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid float value for %s=%r, using %s", name, value, default)
        return default


def _event_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now_item_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _elapsed_ms(start_s: float) -> int:
    return int((time.perf_counter() - start_s) * 1000)


def _add_nvidia_dll_directories() -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return

    for parent in Path(__file__).resolve().parents:
        nvidia_dir = parent / ".venv" / "Lib" / "site-packages" / "nvidia"
        if not nvidia_dir.is_dir():
            continue
        path_entries = []
        for bin_dir in nvidia_dir.glob("*/*bin"):
            if bin_dir.is_dir():
                path_entries.append(str(bin_dir))
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(bin_dir)))
        if path_entries:
            os.environ["PATH"] = f"{os.pathsep.join(path_entries)}{os.pathsep}{os.environ.get('PATH', '')}"
        return


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

    return _normalize_pcm(pcm, channels, sample_width, sample_rate)


def _read_wav_bytes_as_16khz_mono_pcm(wav_bytes: bytes) -> bytes:
    with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        pcm = wav_file.readframes(wav_file.getnframes())

    return _normalize_pcm(pcm, channels, sample_width, sample_rate)


def _normalize_pcm(pcm: bytes, channels: int, sample_width: int, sample_rate: int) -> bytes:
    if sample_width != SAMPLE_WIDTH:
        pcm = audioop.lin2lin(pcm, sample_width, SAMPLE_WIDTH)
    if channels > 1:
        pcm = audioop.tomono(pcm, SAMPLE_WIDTH, 0.5, 0.5)
    if sample_rate != SAMPLE_RATE:
        pcm, _ = audioop.ratecv(pcm, SAMPLE_WIDTH, CHANNELS, sample_rate, SAMPLE_RATE, None)
    return bytes(pcm)


def _float_samples_to_pcm(samples: Any, sample_rate: int) -> bytes:
    numpy = importlib.import_module("numpy")
    sample_array = numpy.asarray(samples, dtype=numpy.float32)
    if sample_array.ndim > 1:
        sample_array = sample_array.reshape(-1)

    sample_array = numpy.clip(sample_array, -1.0, 1.0)
    pcm = (sample_array * 32767.0).astype(numpy.int16).tobytes()
    if sample_rate != SAMPLE_RATE:
        pcm, _ = audioop.ratecv(pcm, SAMPLE_WIDTH, CHANNELS, sample_rate, SAMPLE_RATE, None)
    return bytes(pcm)


def _rms(pcm: bytes) -> int:
    if not pcm:
        return 0
    return audioop.rms(pcm, SAMPLE_WIDTH)


def _chunk_pcm(pcm: bytes, chunk_ms: int = 100) -> list[bytes]:
    bytes_per_ms = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS // 1000
    chunk_size = max(bytes_per_ms * chunk_ms, SAMPLE_WIDTH)
    return [pcm[index : index + chunk_size] for index in range(0, len(pcm), chunk_size)]


def _split_tts_text(text: str, max_chars: int) -> list[str]:
    clean_text = re.sub(r"\s+", " ", text).strip()
    if not clean_text:
        return []

    sentences = [match.group(0).strip() for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", clean_text)]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_tts_sentence(sentence, max_chars))
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


def _split_long_tts_sentence(sentence: str, max_chars: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for word in sentence.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _limit_spoken_text(text: str, max_chars: int) -> str:
    clean_text = re.sub(r"\s+", " ", text).strip()
    if max_chars <= 0 or len(clean_text) <= max_chars:
        return clean_text

    sentences = [match.group(0).strip() for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", clean_text)]
    selected: list[str] = []
    selected_chars = 0
    for sentence in sentences:
        candidate_chars = selected_chars + len(sentence) + (1 if selected else 0)
        if selected and candidate_chars > max_chars:
            break
        if not selected and len(sentence) > max_chars:
            return sentence[: max(0, max_chars - 3)].rstrip() + "..."
        selected.append(sentence)
        selected_chars = candidate_chars

    limited_text = " ".join(selected).strip()
    if limited_text:
        return limited_text
    return clean_text[: max(0, max_chars - 3)].rstrip() + "..."


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


def _strip_tts_markdown(text: str) -> str:
    stripped = text
    stripped = _MARKDOWN_BULLET_RE.sub("", stripped)
    stripped = _MARKDOWN_EMPHASIS_RE.sub(r"\1", stripped)
    stripped = stripped.replace("\\*", "*")
    stripped = stripped.replace("`", "")
    return stripped


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

    decoded = _strip_tts_markdown("".join(speech_chars))
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
        started_s = time.perf_counter()
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
        transcript = result.stdout.strip()
        logger.info("STT command completed in %d ms, transcript_chars=%d", _elapsed_ms(started_s), len(transcript))
        return transcript


class _FasterWhisperStt:
    def __init__(self) -> None:
        self.model_name = _env("LOCAL_BRIDGE_STT_MODEL", "small.en")
        self.device = _env("LOCAL_BRIDGE_STT_DEVICE", "auto")
        self.compute_type = _env("LOCAL_BRIDGE_STT_COMPUTE_TYPE", "default")
        self.language = _env("LOCAL_BRIDGE_STT_LANGUAGE", "en")
        self.beam_size = int(_env("LOCAL_BRIDGE_STT_BEAM_SIZE", "5"))
        self.best_of = int(_env("LOCAL_BRIDGE_STT_BEST_OF", "5"))
        self.hotwords = _env("LOCAL_BRIDGE_STT_HOTWORDS")
        self.initial_prompt = _env("LOCAL_BRIDGE_STT_INITIAL_PROMPT")
        self.model: Any | None = None
        self.lock = asyncio.Lock()

    def _load(self) -> Any:
        if self.model is not None:
            return self.model

        _add_nvidia_dll_directories()
        try:
            faster_whisper = importlib.import_module("faster_whisper")
        except ModuleNotFoundError as exc:
            raise RuntimeError("faster-whisper is not installed in the conversation app environment.") from exc

        model_kwargs = {"device": self.device}
        if self.compute_type != "default":
            model_kwargs["compute_type"] = self.compute_type

        started_s = time.perf_counter()
        self.model = faster_whisper.WhisperModel(self.model_name, **model_kwargs)
        logger.info(
            "Loaded faster-whisper model %s on %s in %d ms",
            self.model_name,
            self.device,
            _elapsed_ms(started_s),
        )
        return self.model

    def _transcribe_sync(self, wav_path: Path) -> str:
        model = self._load()
        segments, _ = model.transcribe(
            str(wav_path),
            language=self.language.strip() or None,
            vad_filter=True,
            beam_size=self.beam_size,
            best_of=self.best_of,
            hotwords=self.hotwords.strip() or None,
            initial_prompt=self.initial_prompt.strip() or None,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    async def transcribe(self, pcm: bytes) -> str:
        started_s = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "input.wav"
            _write_wav(wav_path, pcm)
            async with self.lock:
                transcript = await asyncio.to_thread(self._transcribe_sync, wav_path)
        logger.info(
            "STT faster-whisper completed in %d ms, transcript_chars=%d", _elapsed_ms(started_s), len(transcript)
        )
        return transcript


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


class _KokoroTts:
    def __init__(self) -> None:
        bridge_dir = Path(__file__).parent
        self.model_path = Path(_env("LOCAL_BRIDGE_KOKORO_MODEL", str(bridge_dir / "kokoro" / "kokoro-v1.0.onnx")))
        self.voices_path = Path(_env("LOCAL_BRIDGE_KOKORO_VOICES", str(bridge_dir / "kokoro" / "voices-v1.0.bin")))
        self.voice = _env("LOCAL_BRIDGE_KOKORO_VOICE", "am_eric")
        self.speed = float(_env("LOCAL_BRIDGE_KOKORO_SPEED", "1.0"))
        self.lang = _env("LOCAL_BRIDGE_KOKORO_LANG", "en-us")
        self.kokoro: Any | None = None

    def _load(self) -> Any:
        if self.kokoro is not None:
            return self.kokoro
        if not self.model_path.exists():
            raise RuntimeError(f"Kokoro model not found: {self.model_path}")
        if not self.voices_path.exists():
            raise RuntimeError(f"Kokoro voices file not found: {self.voices_path}")
        try:
            kokoro_module = importlib.import_module("kokoro_onnx")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "kokoro-onnx is not installed. Run: pip install -r requirements-tts-kokoro.txt"
            ) from exc

        self.kokoro = kokoro_module.Kokoro(str(self.model_path), str(self.voices_path))
        return self.kokoro

    def _create_audio(self, text: str) -> tuple[Any, int]:
        kokoro = self._load()
        samples, sample_rate = kokoro.create(text, voice=self.voice, speed=self.speed, lang=self.lang)
        return samples, int(sample_rate)

    async def synthesize(self, text: str) -> bytes:
        text = _speech_text(text)
        if not text:
            return b""
        samples, sample_rate = await asyncio.to_thread(self._create_audio, text)
        return _float_samples_to_pcm(samples, sample_rate)


class _Qwen3HttpTts:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.url = _env("LOCAL_BRIDGE_QWEN_TTS_URL", "http://127.0.0.1:8000/v1/audio/speech")
        self.model = _env("LOCAL_BRIDGE_QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
        self.voice = _env("LOCAL_BRIDGE_QWEN_TTS_VOICE", "Aiden")
        self.language = _env("LOCAL_BRIDGE_QWEN_TTS_LANGUAGE", "English")
        self.instruct = _env("LOCAL_BRIDGE_QWEN_TTS_INSTRUCT")
        self.timeout_s = float(_env("LOCAL_BRIDGE_QWEN_TTS_TIMEOUT_S", "60"))
        self.client = client

    async def synthesize(self, text: str) -> bytes:
        started_s = time.perf_counter()
        text = _speech_text(text)
        if not text:
            return b""

        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "wav",
            "language": self.language,
        }
        if self.instruct:
            payload["instruct"] = self.instruct

        if self.client is not None:
            response = await self.client.post(self.url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(self.url, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            details = exc.response.text.strip()
            raise RuntimeError(f"Qwen3-TTS HTTP failed: {details}") from exc
        pcm = _read_wav_bytes_as_16khz_mono_pcm(response.content)
        logger.info(
            "TTS qwen3tts completed in %d ms, text_chars=%d, pcm_ms=%d",
            _elapsed_ms(started_s),
            len(text),
            len(pcm) // (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS // 1000),
        )
        return pcm


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
        started_s = time.perf_counter()
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
            "messages": _llm_messages_with_local_speech_budget(messages),
            "temperature": _env_float("LOCAL_BRIDGE_TEMPERATURE", 0.7),
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
        result = _LlmResult(
            content=message.get("content") or "",
            tool_calls=message.get("tool_calls") or [],
        )
        logger.info(
            "LLM chat completed in %d ms, model=%s, content_chars=%d, tool_calls=%d",
            _elapsed_ms(started_s),
            self.model,
            len(result.content),
            len(result.tool_calls),
        )
        return result


def _llm_messages_with_local_speech_budget(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_chars = _env_int("LOCAL_BRIDGE_MAX_SPOKEN_CHARS", 220)
    if max_chars <= 0:
        return messages

    budget_instruction = (
        "Local speech synthesis is slow. Keep normal spoken replies under "
        f"{max_chars} characters, preferably one or two short sentences. "
        "Only exceed this when the user explicitly asks for a long answer, recitation, or story."
    )
    if messages and messages[0].get("role") == "system":
        system_message = {**messages[0], "content": f"{messages[0].get('content') or ''}\n\n{budget_instruction}"}
        return [system_message, *messages[1:]]
    return [{"role": "system", "content": budget_instruction}, *messages]


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for part in content:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            text_parts.append(part["text"])
    return " ".join(text_parts)


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
        speech_threshold = _env_int("LOCAL_BRIDGE_VAD_RMS", 350)
        stop_silence_ms = _env_int("LOCAL_BRIDGE_VAD_STOP_MS", 700)
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
        turn_started_s = time.perf_counter()
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

        logger.info("Speech turn transcription ready in %d ms", _elapsed_ms(turn_started_s))
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
        logger.info("Speech turn completed in %d ms", _elapsed_ms(turn_started_s))

    async def respond(self) -> None:
        async with self.response_lock:
            response_started_s = time.perf_counter()
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
                logger.info("Response completed with tool calls in %d ms", _elapsed_ms(response_started_s))
                return

            text, emoji_emotion = _speech_text_and_emoji_emotion(result.content.strip())
            if not self._last_user_requested_long_spoken_response():
                max_spoken_chars = _env_int("LOCAL_BRIDGE_MAX_SPOKEN_CHARS", 220)
                limited_text = _limit_spoken_text(text, max_spoken_chars)
                if limited_text != text:
                    logger.info(
                        "Limited spoken response from %d to %d chars for local TTS",
                        len(text),
                        len(limited_text),
                    )
                    text = limited_text
            emoji_tool_call = None
            if (
                emoji_emotion
                and _env_bool("LOCAL_BRIDGE_EMOJI_EMOTIONS", True)
                and _tool_available(self.tools, "play_emotion")
            ):
                emoji_tool_call = _emotion_tool_call(emoji_emotion)

            if text or emoji_tool_call:
                assistant_response_message: dict[str, Any] = {"role": "assistant", "content": text or None}
                if emoji_tool_call:
                    assistant_response_message["tool_calls"] = [emoji_tool_call]
                self.messages.append(assistant_response_message)

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
                tts_chunks = _split_tts_text(text, _env_int("LOCAL_BRIDGE_TTS_CHUNK_CHARS", 80))
                logger.info("Synthesizing response as %d TTS chunk(s), text_chars=%d", len(tts_chunks), len(text))
                await self._synthesize_and_stream_tts_chunks(tts_chunks, response_id, item_id)

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
            logger.info("Response completed in %d ms, text_chars=%d", _elapsed_ms(response_started_s), len(text))

    async def _synthesize_and_stream_tts_chunks(
        self,
        tts_chunks: list[str],
        response_id: str,
        item_id: str,
    ) -> None:
        next_audio_task: asyncio.Task[bytes] | None = None
        total_chunks = len(tts_chunks)
        for chunk_index, tts_text in enumerate(tts_chunks):
            try:
                if next_audio_task is None:
                    audio_pcm = await self.tts.synthesize(tts_text)
                else:
                    audio_pcm = await next_audio_task

                if chunk_index + 1 < total_chunks:
                    next_audio_task = asyncio.create_task(self.tts.synthesize(tts_chunks[chunk_index + 1]))
                else:
                    next_audio_task = None
            except Exception as exc:
                await self.error(str(exc), "tts_failed")
                return

            logger.info(
                "Streaming TTS chunk %d/%d, text_chars=%d, pcm_ms=%d",
                chunk_index + 1,
                total_chunks,
                len(tts_text),
                len(audio_pcm) // (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS // 1000),
            )
            await self._stream_audio_pcm(audio_pcm, response_id, item_id)

    async def _stream_audio_pcm(self, audio_pcm: bytes, response_id: str, item_id: str) -> None:
        pace = max(0.0, _env_float("LOCAL_BRIDGE_AUDIO_DELTA_PACE", 0.85))
        bytes_per_second = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS
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
            if pace > 0.0:
                await asyncio.sleep((len(chunk) / bytes_per_second) * pace)

    def _last_user_requested_long_spoken_response(self) -> bool:
        for message in reversed(self.messages):
            if message.get("role") != "user":
                continue
            text = _message_text(message.get("content")).lower()
            return bool(
                re.search(r"\b(recite|read|long|full|entire|whole|complete|detailed|story|poem|essay)\b", text)
            )
        return False

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
    provider = _env("LOCAL_BRIDGE_STT_PROVIDER", "").lower()
    if provider == "faster_whisper":
        return _FasterWhisperStt()
    if provider:
        raise RuntimeError("LOCAL_BRIDGE_STT_PROVIDER must be faster_whisper.")

    command = _env("LOCAL_BRIDGE_STT_COMMAND")
    if command:
        return _CommandStt(command)
    return _MissingStt()


def _build_tts_provider() -> _TtsProvider:
    provider = _env("LOCAL_BRIDGE_TTS_PROVIDER", "").lower()
    if provider == "piper":
        return _PiperTts()
    if provider == "kokoro":
        return _KokoroTts()
    if provider == "qwen3tts":
        return _Qwen3HttpTts()
    if provider and provider != "sapi":
        raise RuntimeError("LOCAL_BRIDGE_TTS_PROVIDER must be piper, kokoro, qwen3tts, or sapi.")

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
    port = _env_int("LOCAL_BRIDGE_PORT", DEFAULT_PORT)
    ping_interval = _env_float("LOCAL_BRIDGE_WS_PING_INTERVAL_S", 60.0)
    ping_timeout = _env_float("LOCAL_BRIDGE_WS_PING_TIMEOUT_S", 60.0)
    logger.info("Starting local voice bridge on ws://%s:%s/v1/realtime", host, port)
    async with serve(_handle_connection, host, port, ping_interval=ping_interval, ping_timeout=ping_timeout):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
