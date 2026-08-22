import logging
from typing import Any
from urllib.parse import urlparse

from reachy_mini_conversation_app.image_urls import normalize_image_url
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class ShowImage(Tool):
    """Display a direct image URL in the conversation web UI."""

    name = "show_image"
    description = (
        "Display a direct HTTP or HTTPS image URL in the conversation web UI image preview. "
        "Use this when the user asks to show a picture, image, photo, artwork, or visual reference in the UI. "
        "The image_url must point directly to an image file or image-serving URL, not a generic web page."
    )
    needs_response = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "image_url": {
                "type": "string",
                "description": "Direct HTTP or HTTPS URL for the image to display.",
            },
            "title": {
                "type": "string",
                "description": "Optional short label for the image preview.",
            },
        },
        "required": ["image_url"],
        "additionalProperties": False,
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        """Return UI-display metadata for a direct image URL."""
        del deps
        image_url = normalize_image_url(str(kwargs.get("image_url") or ""))
        title = str(kwargs.get("title") or "").strip()
        logger.info("Tool call: show_image image_url=%s title=%s", image_url[:160], title[:80])

        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"error": "image_url must be a direct HTTP or HTTPS image URL"}

        result: dict[str, Any] = {
            "status": "ok",
            "image_url": image_url,
            "source": "web",
        }
        if title:
            result["title"] = title[:80]
        return result
