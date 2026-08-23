import logging
from typing import Any
from urllib.parse import urlparse

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class ShowWebPage(Tool):
    """Display a web page URL in the conversation web UI."""

    name = "show_web_page"
    description = (
        "Open an HTTP or HTTPS web page from the conversation web UI in a new browser tab or window. "
        "Use this when the user asks to show, open, display, or bring up a website, article, map, document page, "
        "dashboard, search result page, or other normal web page in the UI. "
        "The UI will also provide an open-link fallback if the browser blocks the automatic tab."
    )
    needs_response = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP or HTTPS URL for the web page to display.",
            },
            "title": {
                "type": "string",
                "description": "Optional short label for the web page panel.",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        """Return UI-display metadata for a web page URL."""
        del deps
        url = str(kwargs.get("url") or "").strip()
        title = str(kwargs.get("title") or "").strip()
        logger.info("Tool call: show_web_page url=%s title=%s", url[:160], title[:80])

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"error": "url must be an HTTP or HTTPS web page URL"}

        result: dict[str, Any] = {
            "status": "ok",
            "url": url,
            "source": "web",
        }
        if title:
            result["title"] = title[:80]
        return result
