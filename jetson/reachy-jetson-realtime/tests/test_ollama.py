import os

import httpx
import pytest
from jetson_realtime_probe.server import ask_ollama, ollama_model, ollama_base_url, ollama_timeout_s


pytestmark = pytest.mark.skipif(
    os.getenv("JETSON_REALTIME_RUN_LIVE_TESTS") != "1",
    reason="Ollama integration checks require JETSON_REALTIME_RUN_LIVE_TESTS=1.",
)


@pytest.mark.asyncio
async def test_ollama_lists_expected_probe_model() -> None:
    """Configured Ollama should list the model selected for the probe."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{ollama_base_url()}/api/tags")
    response.raise_for_status()
    names = {model["name"] for model in response.json().get("models", [])}

    assert ollama_model() in names


@pytest.mark.asyncio
async def test_ollama_chat_returns_text() -> None:
    """Configured Ollama should return a non-empty chat response."""
    answer = await ask_ollama("Reply with exactly: jetson ready")

    assert answer
    assert ollama_timeout_s() >= 120.0
