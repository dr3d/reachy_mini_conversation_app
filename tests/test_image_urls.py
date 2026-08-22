from reachy_mini_conversation_app.image_urls import normalize_image_url


def test_normalize_wikimedia_thumbnail_url_uses_next_allowed_width() -> None:
    """Wikimedia blocks hand-built thumbnails that use non-standard widths."""
    result = normalize_image_url(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Reachy.jpg/287px-Reachy.jpg"
    )

    assert result == "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Reachy.jpg/330px-Reachy.jpg"


def test_normalize_wikimedia_thumbnail_url_preserves_svg_render_extension() -> None:
    """SVG thumbnails should stay as rendered PNG thumbnails."""
    result = normalize_image_url(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Logo.svg/135px-Logo.svg.png"
    )

    assert result == "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Logo.svg/250px-Logo.svg.png"
