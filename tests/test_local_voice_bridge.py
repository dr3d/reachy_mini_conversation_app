from local_voice_bridge.server import (
    _KokoroTts,
    _speech_text,
    _build_tts_provider,
    _float_samples_to_pcm,
    _speech_text_and_emoji_emotion,
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


def test_build_tts_provider_accepts_kokoro(monkeypatch) -> None:
    """Kokoro should be selectable as a native bridge TTS provider."""
    monkeypatch.setenv("LOCAL_BRIDGE_TTS_PROVIDER", "kokoro")

    assert isinstance(_build_tts_provider(), _KokoroTts)


def test_float_samples_to_pcm_clips_and_resamples() -> None:
    """Kokoro float samples should become the bridge's 16 kHz mono PCM."""
    pcm = _float_samples_to_pcm([-2.0, -0.5, 0.5, 2.0], 24000)

    assert len(pcm) > 0
    assert len(pcm) % 2 == 0
