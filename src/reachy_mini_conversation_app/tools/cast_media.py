import asyncio
import logging
from typing import Any

from reachy_mini_conversation_app.media_cast import CastMediaClient
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

CAST_ACTIONS: tuple[str, ...] = ("devices", "search_youtube", "play_youtube", "show_image", "stop")


class CastMedia(Tool):
    """Search YouTube and show media on a local Cast receiver."""

    name = "cast_media"
    description = (
        "Search YouTube, play videos, or show direct image URLs on the configured Chromecast-compatible TV. "
        "Use this when the user asks to show, watch, cast, or put YouTube videos or pictures on the TV."
    )
    needs_response = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(CAST_ACTIONS),
                "description": "Media action: list Cast devices, search YouTube, play YouTube, show an image, or stop playback.",
            },
            "query": {
                "type": "string",
                "description": "YouTube search query. For play_youtube, this plays the first matching result.",
            },
            "video_id": {
                "type": "string",
                "description": "YouTube video ID or watch/shorts URL to play directly.",
            },
            "device_name": {
                "type": "string",
                "description": "Optional Cast device name. Defaults to Living Room TV.",
            },
            "image_url": {
                "type": "string",
                "description": "Direct HTTP or HTTPS image URL for show_image. Must point to jpg, jpeg, png, webp, or gif.",
            },
            "title": {
                "type": "string",
                "description": "Optional short title for a cast image.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "Number of YouTube search results to return for search_youtube.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        """Search YouTube or control Cast playback."""
        del deps
        logger.info("Tool call: cast_media args=%s", kwargs)
        action = str(kwargs.get("action") or "").strip().lower()
        client = CastMediaClient()

        try:
            if action == "devices":
                return await asyncio.to_thread(client.list_devices)
            if action == "search_youtube":
                query = str(kwargs.get("query") or "").strip()
                max_results = int(kwargs.get("max_results") or 3)
                return await asyncio.to_thread(client.search_youtube, query, max_results)
            if action == "play_youtube":
                play_query = str(kwargs.get("query") or "").strip() or None
                video_id = str(kwargs.get("video_id") or "").strip() or None
                device_name = str(kwargs.get("device_name") or "").strip() or None
                return await asyncio.to_thread(
                    client.play_youtube,
                    query=play_query,
                    video_id=video_id,
                    device_name=device_name,
                )
            if action == "show_image":
                image_url = str(kwargs.get("image_url") or "").strip()
                title = str(kwargs.get("title") or "").strip() or None
                device_name = str(kwargs.get("device_name") or "").strip() or None
                return await asyncio.to_thread(
                    client.show_image,
                    image_url=image_url,
                    title=title,
                    device_name=device_name,
                )
            if action == "stop":
                device_name = str(kwargs.get("device_name") or "").strip() or None
                return await asyncio.to_thread(client.stop, device_name)
        except ModuleNotFoundError as exc:
            return {"error": f"Missing Cast media dependency: {exc.name}"}
        except ValueError as exc:
            return {"error": str(exc)}

        return {"error": f"Unknown cast media action: {action}"}
