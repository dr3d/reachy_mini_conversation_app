from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from reachy_mini_conversation_app import media_cast
from reachy_mini_conversation_app.media_cast import CastMediaClient, CastMediaSettings, extract_youtube_video_id
from reachy_mini_conversation_app.tools.cast_media import CastMedia
from reachy_mini_conversation_app.tools.core_tools import ToolDependencies


def test_extract_youtube_video_id_accepts_id_watch_and_shorts_urls() -> None:
    """Common YouTube references should normalize to a video ID."""
    assert extract_youtube_video_id("abc123") == "abc123"
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=abc123&t=10") == "abc123"
    assert extract_youtube_video_id("https://youtube.com/shorts/short123") == "short123"
    assert extract_youtube_video_id("https://youtu.be/shortlink123") == "shortlink123"


def test_search_youtube_uses_flat_limited_results(monkeypatch) -> None:
    """YouTube searches should return compact video metadata."""
    captured: dict[str, object] = {}

    class FakeYoutubeDl:
        def __init__(self, options: dict[str, object]) -> None:
            captured["options"] = options

        def __enter__(self) -> "FakeYoutubeDl":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_info(self, query: str, download: bool) -> dict[str, object]:
            captured["query"] = query
            captured["download"] = download
            return {
                "entries": [
                    {
                        "id": "video123",
                        "title": "Reachy video",
                        "channel": "Pollen Robotics",
                        "duration": 53,
                        "url": "https://www.youtube.com/watch?v=video123",
                    }
                ]
            }

    def fake_import_module(name: str) -> object:
        if name == "yt_dlp":
            return SimpleNamespace(YoutubeDL=FakeYoutubeDl)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(media_cast.importlib, "import_module", fake_import_module)

    result = CastMediaClient().search_youtube("reachy mini", max_results=12)

    assert captured["query"] == "ytsearch5:reachy mini"
    assert captured["download"] is False
    assert result["results"] == [
        {
            "video_id": "video123",
            "title": "Reachy video",
            "channel": "Pollen Robotics",
            "duration_s": 53,
            "url": "https://www.youtube.com/watch?v=video123",
        }
    ]


def test_play_youtube_sends_video_to_matching_cast(monkeypatch) -> None:
    """Direct YouTube playback should register the YouTube controller and play the video."""
    played: dict[str, object] = {}
    fake_cast = SimpleNamespace(
        cast_info=SimpleNamespace(
            friendly_name="Living Room TV",
            host=SimpleNamespace(host="192.168.0.45", port=8009),
            model_name="Receiver",
            manufacturer="Test",
            uuid="uuid-1",
        ),
        wait=MagicMock(),
        register_handler=MagicMock(),
    )

    class FakeYoutubeController:
        def __init__(self, timeout: float) -> None:
            played["timeout"] = timeout

        def play_video(self, video_id: str) -> None:
            played["video_id"] = video_id

    fake_pychromecast = SimpleNamespace(
        get_chromecasts=MagicMock(return_value=([fake_cast], object())),
        discovery=SimpleNamespace(stop_discovery=MagicMock()),
    )

    def fake_import_module(name: str) -> object:
        if name == "pychromecast":
            return fake_pychromecast
        if name == "pychromecast.controllers.youtube":
            return SimpleNamespace(YouTubeController=FakeYoutubeController)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(media_cast.importlib, "import_module", fake_import_module)

    result = CastMediaClient(CastMediaSettings(timeout_s=4.0)).play_youtube(video_id="video123")

    assert result["status"] == "ok"
    assert played == {"timeout": 4.0, "video_id": "video123"}
    fake_cast.wait.assert_called_once_with(timeout=4.0)
    fake_cast.register_handler.assert_called_once()
    fake_pychromecast.discovery.stop_discovery.assert_called_once()


def test_play_youtube_resets_receiver_after_pairing_error(monkeypatch) -> None:
    """Stale YouTube receiver pairing should get one app reset and retry."""
    played: list[str] = []
    fake_cast = SimpleNamespace(
        cast_info=SimpleNamespace(
            friendly_name="Living Room TV",
            host=SimpleNamespace(host="192.168.0.45", port=8009),
            model_name="Receiver",
            manufacturer="Test",
            uuid="uuid-1",
        ),
        wait=MagicMock(),
        register_handler=MagicMock(),
        quit_app=MagicMock(),
    )

    class FakeYoutubeController:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def play_video(self, video_id: str) -> None:
            played.append(video_id)
            if len(played) == 1:
                raise RuntimeError(
                    "400 Client Error: screen_ids parameter error for url: "
                    "https://www.youtube.com/api/lounge/pairing/get_lounge_token_batch"
                )

    fake_pychromecast = SimpleNamespace(
        get_chromecasts=MagicMock(return_value=([fake_cast], object())),
        discovery=SimpleNamespace(stop_discovery=MagicMock()),
    )

    def fake_import_module(name: str) -> object:
        if name == "pychromecast":
            return fake_pychromecast
        if name == "pychromecast.controllers.youtube":
            return SimpleNamespace(YouTubeController=FakeYoutubeController)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(media_cast.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(media_cast.time, "sleep", MagicMock())

    result = CastMediaClient(CastMediaSettings(timeout_s=4.0)).play_youtube(video_id="video123")

    assert result["status"] == "ok"
    assert result["recovered"] is True
    assert played == ["video123", "video123"]
    assert fake_cast.register_handler.call_count == 2
    fake_cast.quit_app.assert_called_once_with(timeout=4.0)
    media_cast.time.sleep.assert_called_once_with(1.0)
    fake_pychromecast.discovery.stop_discovery.assert_called_once()


def test_show_image_sends_direct_image_url_to_matching_cast(monkeypatch) -> None:
    """Direct image URLs should play through the Cast media controller."""
    media_controller = SimpleNamespace(
        play_media=MagicMock(),
        block_until_active=MagicMock(),
    )
    fake_cast = SimpleNamespace(
        cast_info=SimpleNamespace(
            friendly_name="Living Room TV",
            host=SimpleNamespace(host="192.168.0.45", port=8009),
            model_name="Receiver",
            manufacturer="Test",
            uuid="uuid-1",
        ),
        wait=MagicMock(),
        media_controller=media_controller,
    )
    fake_pychromecast = SimpleNamespace(
        get_chromecasts=MagicMock(return_value=([fake_cast], object())),
        discovery=SimpleNamespace(stop_discovery=MagicMock()),
    )

    def fake_import_module(name: str) -> object:
        if name == "pychromecast":
            return fake_pychromecast
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(media_cast.importlib, "import_module", fake_import_module)

    result = CastMediaClient(CastMediaSettings(timeout_s=4.0)).show_image(
        image_url="https://example.com/reachy.jpg",
        title="Reachy",
    )

    assert result["status"] == "ok"
    assert result["action"] == "show_image"
    assert result["content_type"] == "image/jpeg"
    fake_cast.wait.assert_called_once_with(timeout=4.0)
    media_controller.play_media.assert_called_once_with(
        "https://example.com/reachy.jpg",
        "image/jpeg",
        title="Reachy",
        thumb="https://example.com/reachy.jpg",
        stream_type="BUFFERED",
        metadata={
            "metadataType": 4,
            "title": "Reachy",
            "images": [{"url": "https://example.com/reachy.jpg"}],
        },
    )
    media_controller.block_until_active.assert_called_once_with(timeout=4.0)
    fake_pychromecast.discovery.stop_discovery.assert_called_once()


def test_show_image_normalizes_wikimedia_thumbnail_before_cast(monkeypatch) -> None:
    """Blocked Wikimedia thumbnail widths should be corrected before casting."""
    media_controller = SimpleNamespace(
        play_media=MagicMock(),
        block_until_active=MagicMock(),
    )
    fake_cast = SimpleNamespace(
        cast_info=SimpleNamespace(
            friendly_name="Living Room TV",
            host=SimpleNamespace(host="192.168.0.45", port=8009),
            model_name="Receiver",
            manufacturer="Test",
            uuid="uuid-1",
        ),
        wait=MagicMock(),
        media_controller=media_controller,
    )
    fake_pychromecast = SimpleNamespace(
        get_chromecasts=MagicMock(return_value=([fake_cast], object())),
        discovery=SimpleNamespace(stop_discovery=MagicMock()),
    )

    def fake_import_module(name: str) -> object:
        if name == "pychromecast":
            return fake_pychromecast
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(media_cast.importlib, "import_module", fake_import_module)

    result = CastMediaClient(CastMediaSettings(timeout_s=4.0)).show_image(
        image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Reachy.jpg/287px-Reachy.jpg"
    )

    assert (
        result["image_url"] == "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Reachy.jpg/330px-Reachy.jpg"
    )
    media_controller.play_media.assert_called_once_with(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Reachy.jpg/330px-Reachy.jpg",
        "image/jpeg",
        title="Reachy image",
        thumb="https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Reachy.jpg/330px-Reachy.jpg",
        stream_type="BUFFERED",
        metadata={
            "metadataType": 4,
            "title": "Reachy image",
            "images": [
                {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Reachy.jpg/330px-Reachy.jpg"}
            ],
        },
    )


def test_show_image_requires_direct_image_url() -> None:
    """Generic web pages should not be sent to the Cast image receiver."""
    result = CastMediaClient(CastMediaSettings(timeout_s=4.0)).show_image(
        image_url="https://example.com/gallery",
    )

    assert result == {"error": "Provide a direct HTTP or HTTPS image URL ending in jpg, jpeg, png, webp, or gif."}


def test_stop_falls_back_to_quitting_cast_app(monkeypatch) -> None:
    """YouTube Cast playback may need the receiver app quit instead of media stop."""
    fake_cast = SimpleNamespace(
        cast_info=SimpleNamespace(
            friendly_name="Living Room TV",
            host=SimpleNamespace(host="192.168.0.45", port=8009),
            model_name="Receiver",
            manufacturer="Test",
            uuid="uuid-1",
        ),
        wait=MagicMock(),
        media_controller=SimpleNamespace(stop=MagicMock(side_effect=RuntimeError("no session"))),
        quit_app=MagicMock(),
    )
    fake_pychromecast = SimpleNamespace(
        get_chromecasts=MagicMock(return_value=([fake_cast], object())),
        discovery=SimpleNamespace(stop_discovery=MagicMock()),
    )

    def fake_import_module(name: str) -> object:
        if name == "pychromecast":
            return fake_pychromecast
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(media_cast.importlib, "import_module", fake_import_module)

    result = CastMediaClient(CastMediaSettings(timeout_s=4.0)).stop()

    assert result["status"] == "ok"
    fake_cast.media_controller.stop.assert_called_once()
    fake_cast.quit_app.assert_called_once_with(timeout=4.0)
    fake_pychromecast.discovery.stop_discovery.assert_called_once()


@pytest.mark.asyncio
async def test_cast_media_tool_returns_missing_target_devices(monkeypatch) -> None:
    """Tool calls should return discovered devices when the configured target is absent."""

    def fake_play_youtube(self: CastMediaClient, **_kwargs: object) -> dict[str, object]:
        return {"error": "Cast device not found: Living Room TV", "devices": [{"name": "Kitchen Display"}]}

    monkeypatch.setattr(CastMediaClient, "play_youtube", fake_play_youtube)
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())

    result = await CastMedia()(deps, action="play_youtube", query="reachy mini")

    assert result == {
        "error": "Cast device not found: Living Room TV",
        "devices": [{"name": "Kitchen Display"}],
    }


@pytest.mark.asyncio
async def test_cast_media_tool_dispatches_show_image(monkeypatch) -> None:
    """The tool should expose image casting as a separate action."""

    def fake_show_image(self: CastMediaClient, **kwargs: object) -> dict[str, object]:
        return {"status": "ok", "action": "show_image", **kwargs}

    monkeypatch.setattr(CastMediaClient, "show_image", fake_show_image)
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())

    result = await CastMedia()(
        deps,
        action="show_image",
        image_url="https://example.com/reachy.png",
        title="Reachy",
    )

    assert result == {
        "status": "ok",
        "action": "show_image",
        "image_url": "https://example.com/reachy.png",
        "title": "Reachy",
        "device_name": None,
    }
