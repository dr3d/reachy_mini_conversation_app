from unittest.mock import MagicMock

import pytest

from reachy_mini_conversation_app.tools.core_tools import ToolDependencies
from reachy_mini_conversation_app.tools.show_web_page import ShowWebPage


@pytest.mark.asyncio
async def test_show_web_page_accepts_http_url() -> None:
    """The display tool should return browser web-page metadata for web URLs."""
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())

    result = await ShowWebPage()(deps, url="https://example.com/reachy", title="Reachy")

    assert result == {
        "status": "ok",
        "url": "https://example.com/reachy",
        "source": "web",
        "title": "Reachy",
    }


@pytest.mark.asyncio
async def test_show_web_page_rejects_non_http_urls() -> None:
    """Only HTTP(S) web page URLs should be accepted for display."""
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())

    result = await ShowWebPage()(deps, url="file:///secret.html")

    assert result == {"error": "url must be an HTTP or HTTPS web page URL"}
