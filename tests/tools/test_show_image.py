from unittest.mock import MagicMock

import pytest

from reachy_mini_conversation_app.tools.core_tools import ToolDependencies
from reachy_mini_conversation_app.tools.show_image import ShowImage


@pytest.mark.asyncio
async def test_show_image_accepts_direct_http_image_url() -> None:
    """The display tool should return browser image metadata for direct URLs."""
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())

    result = await ShowImage()(deps, image_url="https://example.com/reachy.jpg", title="Reachy")

    assert result == {
        "status": "ok",
        "image_url": "https://example.com/reachy.jpg",
        "source": "web",
        "title": "Reachy",
    }


@pytest.mark.asyncio
async def test_show_image_normalizes_wikimedia_thumbnails() -> None:
    """Blocked Wikimedia thumbnail widths should be corrected before display."""
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())

    result = await ShowImage()(
        deps,
        image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Reachy.jpg/287px-Reachy.jpg",
    )

    assert (
        result["image_url"] == "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Reachy.jpg/330px-Reachy.jpg"
    )


@pytest.mark.asyncio
async def test_show_image_rejects_non_http_urls() -> None:
    """Only web image URLs should be accepted for display."""
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())

    result = await ShowImage()(deps, image_url="file:///secret.jpg")

    assert result == {"error": "image_url must be a direct HTTP or HTTPS image URL"}
