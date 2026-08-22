from urllib.parse import urlparse, urlunparse


IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
WIKIMEDIA_THUMBNAIL_STEPS = (20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840)


def image_content_type(image_url: str) -> str | None:
    """Return the image content type inferred from a URL path."""
    path = urlparse(image_url).path.casefold()
    for suffix, content_type in IMAGE_CONTENT_TYPES.items():
        if path.endswith(suffix):
            return content_type
    return None


def normalize_image_url(image_url: str) -> str:
    """Normalize direct image URLs for browser/receiver display."""
    candidate = image_url.strip()
    return _normalize_wikimedia_thumbnail_url(candidate)


def _normalize_wikimedia_thumbnail_url(image_url: str) -> str:
    parsed = urlparse(image_url)
    if (parsed.hostname or "").casefold() != "upload.wikimedia.org":
        return image_url
    path_parts = parsed.path.split("/")
    if "thumb" not in path_parts or not path_parts[-1]:
        return image_url

    render_name = path_parts[-1]
    separator_index = render_name.find("px-")
    if separator_index <= 0:
        return image_url
    try:
        requested_width = int(render_name[:separator_index])
    except ValueError:
        return image_url

    standard_width = _next_wikimedia_thumbnail_step(requested_width)
    if standard_width == requested_width:
        return image_url
    path_parts[-1] = f"{standard_width}px-{render_name[separator_index + 3 :]}"
    return urlunparse(parsed._replace(path="/".join(path_parts)))


def _next_wikimedia_thumbnail_step(requested_width: int) -> int:
    for width in WIKIMEDIA_THUMBNAIL_STEPS:
        if requested_width <= width:
            return width
    return WIKIMEDIA_THUMBNAIL_STEPS[-1]
