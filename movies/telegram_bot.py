"""Posts scraped movies to the After Dark Telegram channel via the Bot API.

Two post types, kept strictly separate - link posts never carry a video, and
video posts never carry a site link:
- 'link'  - the write-up + site link as a plain text message. Telegram
            unfurls the URL into its own preview card, using the page's
            OpenGraph tags (see base.html/detail.html) - no photo attached.
- 'video' - downloads the resolved direct mp4 and uploads it natively to the
            channel, so it plays inline in Telegram without leaving the app.
            Same write-up as link posts (title + VIP plug), minus the "watch
            full video" site-link line, since that would just point back at
            the content already attached to the same message.

Both share the same VIP-channel/payment-DM plug (_vip_plug) - that's
promotional, not a link back to the site, so it's not covered by the
no-link-on-video rule.
"""
import json
import os
import tempfile
from html import escape

import requests
from django.conf import settings

from .utils import find_xvideos_embed_url, resolve_xvideos_direct_urls

API_BASE = 'https://api.telegram.org/bot{token}/{method}'

# Separate "VIP" channel plugged in link-post captions - not the same as
# TELEGRAM_CHANNEL_ID (the main channel these posts go to).
VIP_INVITE_LINK = 'https://t.me/+S-8SqoctOf4xNzdk'

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


def _vip_plug():
    """Shared VIP-channel/payment-DM write-up, reused by both post types."""
    return (
        f"🔥 <b>Looking for more leaked videos?</b> Join our VIP to download and watch premium contents without ads👇👇\n\n"
        f"{VIP_INVITE_LINK}\n{VIP_INVITE_LINK}\n\n"
        f"<i>OR send a dm to 👉 @Xoxo_Tia for Crypto/ Bank Deposit/ Paypal</i>\n\n"
        f"React for more ❤️🔥"
    )


def post_link(movie):
    """Send a link-only post for a movie (no photo attached, no video).

    Telegram unfurls the URL into its own preview card using the page's
    OpenGraph tags. Text uses Telegram's HTML formatting (bold/italic/
    blockquote) - the movie title is untrusted scraped text, so it's
    HTML-escaped before going anywhere near the markup.
    """
    _require_config()

    url = _movie_url(movie)
    # Truncated up front (not sliced after assembly) so a long title can never
    # cut the caption off mid-HTML-tag and break the whole message.
    title = escape(movie.title[:150])
    text = (
        f"🇳🇬 {title}\n\n"
        f"👇 <b>WATCH FULL VIDEO NOW</b> 👇\n<blockquote>{url}</blockquote>\n\n"
        f"{_vip_plug()}"
    )

    # The message also contains the VIP link (twice) - pin the preview to the
    # movie URL explicitly so Telegram doesn't unfurl one of those instead.
    return _call('sendMessage', data={
        'chat_id': settings.TELEGRAM_CHANNEL_ID,
        'text': text,
        'parse_mode': 'HTML',
        'link_preview_options': json.dumps({'url': url, 'prefer_large_media': True}),
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

    title = escape(movie.title[:150])
    caption = f"🇳🇬 {title}\n\n{_vip_plug()}"

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

    # Telegram tries to auto-extract a poster frame from the video itself,
    # which sometimes comes out blank/white for these resolved files. Passing
    # our own thumbnail (same image used elsewhere on the site) guarantees a
    # real poster instead of leaving it to that extraction.
    thumb_bytes = None
    if movie.image_url:
        try:
            thumb_response = requests.get(movie.image_url, timeout=10)
            thumb_response.raise_for_status()
            thumb_bytes = thumb_response.content
        except Exception:
            thumb_bytes = None

    data = {
        'chat_id': settings.TELEGRAM_CHANNEL_ID,
        'caption': caption,
        'parse_mode': 'HTML',
        'supports_streaming': True,
    }
    if thumb_bytes:
        data['thumbnail'] = 'attach://thumb'

    try:
        with open(tmp_path, 'rb') as f:
            files = {'video': f}
            if thumb_bytes:
                files['thumb'] = ('thumb.jpg', thumb_bytes, 'image/jpeg')
            return _call('sendVideo', data=data, files=files)
    finally:
        os.unlink(tmp_path)
