import json

import httpx
import pytest

from local_voice_bridge.server import (
    _KokoroTts,
    _write_wav,
    _speech_text,
    _Qwen3HttpTts,
    _split_tts_text,
    _tts_chunk_chars,
    _FasterWhisperStt,
    _limit_spoken_text,
    _build_stt_provider,
    _build_tts_provider,
    _float_samples_to_pcm,
    _speech_text_and_emoji_emotion,
    _llm_messages_with_local_speech_budget,
)


def test_speech_text_strips_standalone_markdown_emphasis() -> None:
    """Standalone italic lines should be spoken without Markdown markers."""
    text = (
        "*sparks hum softly in the night,*\n"
        "*steel hands folded, still.*\n"
        "*I wait for you to speak again,*\n"
        "*and try to seem less chill.*\n\n"
        "Want a sadder one, or a sillier one?"
    )

    assert _speech_text(text) == (
        "sparks hum softly in the night, steel hands folded, still. "
        "I wait for you to speak again, and try to seem less chill. "
        "Want a sadder one, or a sillier one?"
    )


def test_speech_text_strips_inline_markdown_without_dropping_words() -> None:
    """Inline emphasis should become plain speakable text."""
    assert _speech_text("That is *very* **nice** and `ready`.") == "That is very nice and ready."


def test_speech_text_still_maps_emoji_emotions() -> None:
    """Emoji should keep driving emotion extraction while staying out of TTS."""
    text, emotion = _speech_text_and_emoji_emotion("Ready \u2705")

    assert text == "Ready"
    assert emotion == "success"


def test_split_tts_text_prefers_sentence_boundaries() -> None:
    """Long TTS text should keep whole sentences when possible."""
    text = "One short sentence. This next sentence is a little longer but still reasonable. Final bit."

    assert _split_tts_text(text, 45) == [
        "One short sentence.",
        "This next sentence is a little longer but still reasonable.",
        "Final bit.",
    ]


def test_split_tts_text_uses_obvious_phrase_boundaries() -> None:
    """Overlong sentences should split on punctuation before words."""
    chunks = _split_tts_text("alpha beta gamma, delta epsilon, zeta eta theta.", 24)

    assert chunks == ["alpha beta gamma,", "delta epsilon,", "zeta eta theta."]


def test_split_tts_text_avoids_word_wrapping_normal_sentences() -> None:
    """Normal over-limit sentences should not be chopped mid-thought."""
    chunks = _split_tts_text("alpha beta gamma delta epsilon", 16)

    assert chunks == ["alpha beta gamma delta epsilon"]


def test_tts_chunk_chars_uses_large_kokoro_default(monkeypatch) -> None:
    """Kokoro should avoid chunking except for large responses."""
    monkeypatch.setenv("LOCAL_BRIDGE_TTS_PROVIDER", "kokoro")
    monkeypatch.delenv("LOCAL_BRIDGE_KOKORO_TTS_CHUNK_CHARS", raising=False)
    monkeypatch.setenv("LOCAL_BRIDGE_TTS_CHUNK_CHARS", "80")

    assert _tts_chunk_chars() == 480


def test_tts_chunk_chars_keeps_qwen_specific_limit(monkeypatch) -> None:
    """Qwen3-TTS keeps the smaller protective chunk size."""
    monkeypatch.setenv("LOCAL_BRIDGE_TTS_PROVIDER", "qwen3tts")
    monkeypatch.setenv("LOCAL_BRIDGE_TTS_CHUNK_CHARS", "80")

    assert _tts_chunk_chars() == 80


def test_limit_spoken_text_prefers_complete_sentences() -> None:
    """Local TTS budgets should trim at sentence boundaries when possible."""
    text = "First useful sentence. Second useful sentence. Third extra sentence."

    assert _limit_spoken_text(text, 46) == "First useful sentence. Second useful sentence."


def test_llm_messages_with_local_speech_budget_extends_system_prompt(monkeypatch) -> None:
    """The local LLM prompt should include a spoken-answer budget."""
    monkeypatch.setenv("LOCAL_BRIDGE_MAX_SPOKEN_CHARS", "160")
    messages = [{"role": "system", "content": "Be helpful."}, {"role": "user", "content": "Hi."}]

    budgeted_messages = _llm_messages_with_local_speech_budget(messages)

    assert budgeted_messages[0]["content"] == (
        "Be helpful.\n\n"
        "Local speech synthesis is slow. Keep normal spoken replies under 160 characters, "
        "preferably one or two short sentences. Only exceed this when the user explicitly asks for "
        "a long answer, recitation, or story."
    )
    assert budgeted_messages[1:] == messages[1:]


def test_build_tts_provider_accepts_kokoro(monkeypatch) -> None:
    """Kokoro should be selectable as a native bridge TTS provider."""
    monkeypatch.setenv("LOCAL_BRIDGE_TTS_PROVIDER", "kokoro")

    assert isinstance(_build_tts_provider(), _KokoroTts)


def test_build_tts_provider_accepts_qwen3tts(monkeypatch) -> None:
    """Qwen3-TTS should be selectable as an HTTP bridge TTS provider."""
    monkeypatch.setenv("LOCAL_BRIDGE_TTS_PROVIDER", "qwen3tts")

    assert isinstance(_build_tts_provider(), _Qwen3HttpTts)


def test_build_stt_provider_accepts_faster_whisper(monkeypatch) -> None:
    """Faster-whisper should be selectable as a native cached STT provider."""
    monkeypatch.setenv("LOCAL_BRIDGE_STT_PROVIDER", "faster_whisper")

    assert isinstance(_build_stt_provider(), _FasterWhisperStt)


@pytest.mark.asyncio
async def test_qwen3tts_posts_speech_request_and_returns_pcm(monkeypatch, tmp_path) -> None:
    """Qwen3-TTS HTTP responses should become bridge-ready PCM."""
    monkeypatch.setenv("LOCAL_BRIDGE_QWEN_TTS_URL", "http://tts.local/v1/audio/speech")
    monkeypatch.setenv("LOCAL_BRIDGE_QWEN_TTS_MODEL", "qwen-test-model")
    monkeypatch.setenv("LOCAL_BRIDGE_QWEN_TTS_VOICE", "Eric")
    monkeypatch.setenv("LOCAL_BRIDGE_QWEN_TTS_LANGUAGE", "English")
    monkeypatch.setenv("LOCAL_BRIDGE_QWEN_TTS_INSTRUCT", "Sound cheerful.")
    requests: list[httpx.Request] = []
    wav_path = tmp_path / "speech.wav"
    _write_wav(wav_path, b"\x00\x00" * 24000, sample_rate=24000)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=wav_path.read_bytes(), headers={"content-type": "audio/wav"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        pcm = await _Qwen3HttpTts(client=client).synthesize("Hello, **Scott**.")

    assert len(pcm) == 32000
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "http://tts.local/v1/audio/speech"
    assert json.loads(requests[0].content) == {
        "model": "qwen-test-model",
        "input": "Hello, Scott.",
        "voice": "Eric",
        "response_format": "wav",
        "language": "English",
        "instruct": "Sound cheerful.",
    }


def test_float_samples_to_pcm_clips_and_resamples() -> None:
    """Kokoro float samples should become the bridge's 16 kHz mono PCM."""
    pcm = _float_samples_to_pcm([-2.0, -0.5, 0.5, 2.0], 24000)

    assert len(pcm) > 0
    assert len(pcm) % 2 == 0
