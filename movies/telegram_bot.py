"""Posts scraped movies to the After Dark Telegram channel via the Bot API.

Two post types:
- 'link'  - thumbnail + caption + link back to the movie's page on the site.
- 'video' - downloads the resolved direct mp4 and uploads it natively to the
            channel, so it plays inline in Telegram without leaving the app.
"""
import io
import os
import tempfile

import requests
from django.conf import settings
from PIL import Image, ImageDraw

from .utils import find_xvideos_embed_url, resolve_xvideos_direct_urls

API_BASE = 'https://api.telegram.org/bot{token}/{method}'

# Classic Telegram Bot API upload limit. Files above this are rejected by
# Telegram, so we check before downloading anything.
MAX_VIDEO_BYTES = 50 * 1024 * 1024


class TelegramPostError(Exception):
    pass


def _require_config():
    if not settings.TELEGRAM_BOT_TOKEN:
        raise TelegramPostError('TELEGRAM_BOT_TOKEN is not set (see .env.example)')
    if not settings.TELEGRAM_CHANNEL_ID:
        raise TelegramPostError('TELEGRAM_CHANNEL_ID is not set (see .env.example)')


def _call(method, data=None, files=None):
    url = API_BASE.format(token=settings.TELEGRAM_BOT_TOKEN, method=method)
    response = requests.post(url, data=data, files=files, timeout=120)
    payload = response.json()
    if not payload.get('ok'):
        raise TelegramPostError(payload.get('description', 'Unknown Telegram API error'))
    return payload['result']


def _movie_url(movie):
    return f"{settings.SITE_URL.rstrip('/')}{movie.get_absolute_url()}"


def _thumbnail_with_play_button(image_url):
    """Download a thumbnail and draw a play-button icon on top of it.

    Sending this composited image ourselves (instead of just linking to the
    movie page and letting Telegram generate its own preview) means every
    post looks like a consistent video card - Telegram's auto-generated link
    previews pull whatever OpenGraph image/branding the source site happens
    to have, which looks inconsistent post to post.
    """
    response = requests.get(image_url, timeout=15)
    response.raise_for_status()

    image = Image.open(io.BytesIO(response.content)).convert('RGBA')
    width, height = image.size

    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    radius = int(min(width, height) * 0.16)
    cx, cy = width // 2, height // 2
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(220, 38, 38, 220),
    )

    triangle_size = radius * 0.9
    offset = triangle_size * 0.15  # nudge right so the triangle looks visually centered
    draw.polygon(
        [
            (cx - triangle_size / 2 + offset, cy - triangle_size / 2),
            (cx - triangle_size / 2 + offset, cy + triangle_size / 2),
            (cx + triangle_size / 2 + offset, cy),
        ],
        fill=(255, 255, 255, 255),
    )

    composited = Image.alpha_composite(image, overlay).convert('RGB')
    buffer = io.BytesIO()
    composited.save(buffer, format='JPEG', quality=90)
    buffer.seek(0)
    return buffer


def post_link(movie):
    """Send a thumbnail + caption + link post for a movie."""
    _require_config()

    caption = f"{movie.title}\n\n{_movie_url(movie)}"
    caption = caption[:1024]

    if movie.image_url:
        try:
            photo = _thumbnail_with_play_button(movie.image_url)
            return _call('sendPhoto', data={
                'chat_id': settings.TELEGRAM_CHANNEL_ID,
                'caption': caption,
            }, files={'photo': ('thumbnail.jpg', photo, 'image/jpeg')})
        except Exception:
            # Fall back to the plain thumbnail URL if compositing fails for
            # any reason (bad image data, unreachable host, etc.)
            return _call('sendPhoto', data={
                'chat_id': settings.TELEGRAM_CHANNEL_ID,
                'photo': movie.image_url,
                'caption': caption,
            })

    return _call('sendMessage', data={
        'chat_id': settings.TELEGRAM_CHANNEL_ID,
        'text': caption,
    })


def post_video(movie):
    """Download the movie's resolved direct mp4 and upload it natively.

    Raises TelegramPostError if there's no resolvable source or the file is
    too large for the Bot API - the caller should fall back to another movie.
    """
    _require_config()

    embed_url = find_xvideos_embed_url(movie)
    if not embed_url:
        raise TelegramPostError('No resolvable xvideos source for this movie')

    direct_urls = resolve_xvideos_direct_urls(embed_url)
    # Prefer the smaller file - keeps us comfortably under the upload limit.
    video_url = direct_urls.get('low') or direct_urls.get('high')
    if not video_url:
        raise TelegramPostError('Could not resolve a direct video URL')

    head = requests.head(video_url, timeout=15, allow_redirects=True)
    content_length = int(head.headers.get('Content-Length', 0))
    if content_length and content_length > MAX_VIDEO_BYTES:
        raise TelegramPostError(
            f'Video is {content_length / 1024 / 1024:.1f}MB, over the {MAX_VIDEO_BYTES // 1024 // 1024}MB Bot API limit'
        )

    caption = movie.title[:1024]

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        tmp_path = tmp.name
        with requests.get(video_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            downloaded = 0
            for chunk in r.iter_content(chunk_size=1024 * 256):
                downloaded += len(chunk)
                if downloaded > MAX_VIDEO_BYTES:
                    raise TelegramPostError('Video exceeded the size limit while downloading')
                tmp.write(chunk)

    try:
        with open(tmp_path, 'rb') as f:
            return _call('sendVideo', data={
                'chat_id': settings.TELEGRAM_CHANNEL_ID,
                'caption': caption,
                'supports_streaming': True,
            }, files={'video': f})
    finally:
        os.unlink(tmp_path)
