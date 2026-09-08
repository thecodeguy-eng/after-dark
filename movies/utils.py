import re
import cloudscraper

# xvideos signs these with a short-lived expiry token, so they must be
# resolved on-demand (e.g. when a visitor clicks Download) rather than
# scraped once and stored - a cached copy would be dead within a few hours.
XVIDEOS_URL_PATTERNS = {
    'low': re.compile(r"setVideoUrlLow\('([^']+)'\)"),
    'high': re.compile(r"setVideoUrlHigh\('([^']+)'\)"),
    'hls': re.compile(r"setVideoHLS\('([^']+)'\)"),
}


def find_xvideos_embed_url(movie):
    """Return the movie's xvideos embedframe URL from video_sources, if any."""
    return next(
        (source.get('url') for source in (movie.video_sources or [])
         if 'xvideos.com/embedframe' in source.get('url', '')),
        None
    )


def resolve_xvideos_direct_urls(embed_url, timeout=15):
    """Fetch an xvideos embedframe page and pull the signed direct video URLs
    (mp4 low/high quality and HLS) out of its inline html5player script."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://pornbox247.site/",
    }

    # This runs inside the long-lived gunicorn worker on every video
    # watch/download, so the scraper's session (and its connection pool)
    # must be explicitly closed - cloudscraper.create_scraper() left
    # unclosed here was leaking a file descriptor per call until the
    # process hit the OS's open-file limit under real traffic.
    with cloudscraper.create_scraper() as scraper:
        response = scraper.get(embed_url, headers=headers, timeout=timeout)
        response.raise_for_status()
        html = response.text

    urls = {}
    for key, pattern in XVIDEOS_URL_PATTERNS.items():
        match = pattern.search(html)
        if match:
            urls[key] = match.group(1)
    return urls
