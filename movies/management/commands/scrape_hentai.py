from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from movies.models import Movie, Category, Tag, Series, Episode
import requests
from bs4 import BeautifulSoup
import re
import cloudscraper 
from urllib.parse import urlparse, unquote
import json
import pytz
from datetime import datetime

API_URL = 'https://hentaiplay.net/wp-json/wp/v2/posts/'

KNOWN_DOWNLOAD_DOMAINS = [
    'streamtape.com', 'hentaiplanet.info', 'mega.nz', 'drive.google.com',
    'mediafire.com', 'pixeldrain.com', 'terabox.com', 'onedrive.live.com',
    'downloadwella.com', 'netnaijafiles.xyz', 'loadedfiles.org',
    'sabishares.com', 'meetdownload.com'
]

FILE_EXTENSIONS = ['.mp4', '.mkv', '.zip', '.rar', '.srt', '.webm']

def parse_wordpress_date(date_string):
    """Parse WordPress date string to a timezone-aware datetime object"""
    if not date_string:
        return timezone.now()

    try:
        # Replace Z with +00:00 for UTC
        date_string = date_string.replace('Z', '+00:00')
        naive_dt = datetime.fromisoformat(date_string)
        
        # If already aware, return it directly
        if timezone.is_aware(naive_dt):
            return naive_dt
        
        # Otherwise, make it explicitly aware in UTC
        return pytz.UTC.localize(naive_dt)
    except Exception:
        return timezone.now()

def extract_video_sources(soup):
    """Extract video sources from HTML content"""
    video_sources = []
    
    # Look for video tags with source
    videos = soup.find_all('video')
    for video in videos:
        sources = video.find_all('source')
        for source in sources:
            if source.get('src'):
                video_sources.append({
                    'url': source['src'],
                    'type': source.get('type', 'video/mp4'),
                    'label': 'Source 1'
                })
    
    # Look for iframes (embedded videos)
    iframes = soup.find_all('iframe')
    for i, iframe in enumerate(iframes, 1):
        if iframe.get('src'):
            video_sources.append({
                'url': iframe['src'],
                'type': 'iframe',
                'label': f'Source {i + len(video_sources)}'
            })
    
    return video_sources

def extract_download_links(soup):
    """Extract download links from HTML content"""
    download_links = []
    
    # Look for download buttons and links
    download_selectors = [
        'a[href*="download"]',
        'a[class*="download"]',
        'a[class*="btn"]',
        '.su-button',
        '.download',
    ]
    
    for selector in download_selectors:
        links = soup.select(selector)
        for link in links:
            href = link.get('href')
            if href and any(domain in href.lower() for domain in KNOWN_DOWNLOAD_DOMAINS):
                download_links.append({
                    'url': href,
                    'label': link.get_text().strip() or 'Download',
                    'type': 'direct'
                })
    
    return download_links

def extract_series_info(title):
    """Extract series information from title"""
    # Pattern for episode titles like "Series Name Episode X"
    episode_pattern = re.search(r'(.+?)\s+Episode\s+(\d+)', title, re.IGNORECASE)
    if episode_pattern:
        series_name = episode_pattern.group(1).strip()
        episode_num = int(episode_pattern.group(2))
        return series_name, episode_num, 1  # season 1 by default
    
    # Pattern for season/episode like "Series S01E01" or "Series Season 1 Episode 1"
    season_episode_pattern = re.search(r'(.+?)\s+(?:S(\d+)E(\d+)|Season\s+(\d+)\s+Episode\s+(\d+))', title, re.IGNORECASE)
    if season_episode_pattern:
        series_name = season_episode_pattern.group(1).strip()
        if season_episode_pattern.group(2):  # S01E01 format
            season_num = int(season_episode_pattern.group(2))
            episode_num = int(season_episode_pattern.group(3))
        else:  # Season X Episode Y format
            season_num = int(season_episode_pattern.group(4))
            episode_num = int(season_episode_pattern.group(5))
        return series_name, episode_num, season_num
    
    return None, None, None

class Command(BaseCommand):
    help = 'Scrape content from hentaiplay.net and update database'

    def handle(self, *args, **options):
        from django.db import connection
        import time
        
        page = 1
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while True:
            try:
                print(f"\n🌐 Fetching page {page}...")
                scraper = cloudscraper.create_scraper()
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                    "Referer": "https://hentaiplay.net/",
                }

                response = scraper.get(API_URL, params={'page': page, 'per_page': 20}, headers=headers, timeout=15)
                response.raise_for_status()
                data = response.json()
                
            except requests.exceptions.HTTPError as http_err:
                if response.status_code == 404:
                    print("✅ All pages processed.")
                    break
                print(f"🔥 HTTP error: {http_err}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print(f"❌ Too many consecutive errors ({consecutive_errors}). Stopping.")
                    return
                time.sleep(5)
                continue
            except Exception as e:
                print(f"🔥 Request failed: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print(f"❌ Too many consecutive errors ({consecutive_errors}). Stopping.")
                    return
                connection.close()
                time.sleep(5)
                continue

            consecutive_errors = 0

            if not data:
                print("✅ No data returned. Finished.")
                break

            for item in data:
                try:
                    self.process_item(item, scraper, headers)
                except Exception as e:
                    print(f"💥 Error processing item: {e}")
                    continue

            page += 1

    def process_item(self, item, scraper, headers):
        """Process individual item from API"""
        wp_id = item.get('id')
        raw_title = item.get('title', {}).get('rendered', '').strip()
        
        if not raw_title or not wp_id:
            print("⚠️ Skipped: missing title or ID.")
            return

        print(f"\n🎬 Processing: {raw_title} (ID: {wp_id})")
        
        # Parse content
        content_html = item.get('content', {}).get('rendered', '')
        excerpt_html = item.get('excerpt', {}).get('rendered', '')
        
        soup = BeautifulSoup(content_html, 'html.parser')
        excerpt_soup = BeautifulSoup(excerpt_html, 'html.parser')
        
        # Clean title and create slug
        clean_title = re.sub(r'<[^>]+>', '', raw_title).strip()
        slug = slugify(clean_title)
        
        # Parse dates
        date = parse_wordpress_date(item.get('date', ''))
        date_gmt = parse_wordpress_date(item.get('date_gmt', ''))
        modified = parse_wordpress_date(item.get('modified', ''))
        modified_gmt = parse_wordpress_date(item.get('modified_gmt', ''))
        
        # Extract video sources and download links
        video_sources = extract_video_sources(soup)
        download_links = extract_download_links(soup)
        
        print(f"📹 Found {len(video_sources)} video source(s)")
        print(f"⬇️ Found {len(download_links)} download link(s)")
        
        # Get or create movie
        movie, created = Movie.objects.get_or_create(
            wp_id=wp_id,
            defaults={
                'title': clean_title,
                'slug': slug,
                'content': soup.get_text() if soup else '',
                'excerpt': excerpt_soup.get_text() if excerpt_soup else '',
                'date': date,
                'date_gmt': date_gmt,
                'modified': modified,
                'modified_gmt': modified_gmt,
                'status': item.get('status', 'publish'),
                'post_type': item.get('type', 'post'),
                'featured_media_id': item.get('featured_media'),
                'video_sources': video_sources,
                'download_links': download_links,
                'author_id': item.get('author', 1),
                'comment_status': item.get('comment_status', 'open'),
                'ping_status': item.get('ping_status', 'open'),
                'is_sticky': item.get('sticky', False),
                'scraped': True,
            }
        )
        
        if created:
            print(f"✅ Created new movie: {clean_title}")
        else:
            # Update existing movie
            updated = False
            if movie.video_sources != video_sources:
                movie.video_sources = video_sources
                updated = True
            if movie.download_links != download_links:
                movie.download_links = download_links
                updated = True
            if movie.modified != modified:
                movie.modified = modified
                movie.modified_gmt = modified_gmt
                updated = True
                
            if updated:
                movie.save()
                print(f"🔄 Updated movie: {clean_title}")
            else:
                print(f"ℹ️ No changes for: {clean_title}")
        
        # Get featured image
        if movie.featured_media_id and not movie.image_url:
            try:
                img_response = scraper.get(
                    f"https://hentaiplay.net/wp-json/wp/v2/media/{movie.featured_media_id}", 
                    headers=headers,
                    timeout=10
                )
                if img_response.status_code == 200:
                    img_data = img_response.json()
                    movie.image_url = img_data.get('source_url', '')
                    movie.save(update_fields=['image_url'])
                    print(f"🖼️ Added image: {movie.image_url}")
            except Exception as e:
                print(f"⚠️ Failed to get image: {e}")
        
        # Process categories
        for cat_id in item.get('categories', []):
            try:
                cat_response = scraper.get(
                    f"https://hentaiplay.net/wp-json/wp/v2/categories/{cat_id}",
                    headers=headers,
                    timeout=10
                )
                if cat_response.status_code == 200:
                    cat_data = cat_response.json()
                    cat_name = cat_data.get('name', '')
                    if cat_name:
                        category, _ = Category.objects.get_or_create(
                            name=cat_name,
                            defaults={'slug': slugify(cat_name)}
                        )
                        movie.categories.add(category)
                        print(f"📁 Added category: {cat_name}")
            except Exception as e:
                print(f"⚠️ Failed to get category {cat_id}: {e}")
        
        # Process tags
        for tag_id in item.get('tags', []):
            try:
                tag_response = scraper.get(
                    f"https://hentaiplay.net/wp-json/wp/v2/tags/{tag_id}",
                    headers=headers,
                    timeout=10
                )
                if tag_response.status_code == 200:
                    tag_data = tag_response.json()
                    tag_name = tag_data.get('name', '')
                    if tag_name:
                        tag, _ = Tag.objects.get_or_create(
                            name=tag_name,
                            defaults={'slug': slugify(tag_name)}
                        )
                        movie.tags.add(tag)
                        print(f"🏷️ Added tag: {tag_name}")
            except Exception as e:
                print(f"⚠️ Failed to get tag {tag_id}: {e}")
        
        # Check if this is part of a series and create episode record
        series_name, episode_num, season_num = extract_series_info(clean_title)
        if series_name and episode_num:
            series, _ = Series.objects.get_or_create(
                name=series_name,
                defaults={'slug': slugify(series_name)}
            )
            
            episode, episode_created = Episode.objects.get_or_create(
                series=series,
                season_number=season_num,
                episode_number=episode_num,
                defaults={'movie': movie}
            )
            
            if episode_created:
                print(f"📺 Created episode: {series_name} S{season_num:02d}E{episode_num:02d}")
            
        print(f"✨ Completed processing: {clean_title}")