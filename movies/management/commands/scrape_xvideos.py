from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from movies.models import Movie, Category
import re
import time
import cloudscraper
from urllib.parse import urljoin
from bs4 import BeautifulSoup

BASE_URL = 'https://www.xvideos.com'

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.xvideos.com/",
}


def category_display_name(category_slug):
    """'Big_Ass-24' -> 'Big Ass'"""
    name = re.sub(r'-\d+$', '', category_slug)
    return name.replace('_', ' ').strip()


CATEGORY_LINK_RE = re.compile(r'^/c/[\w]+-\d+$')


def fetch_all_categories(scraper):
    """Discover every browsable category slug xvideos lists on its homepage,
    e.g. [('Big_Ass-24', 'Big Ass'), ('Anal-12', 'Anal'), ...]."""
    response = scraper.get(BASE_URL + '/', headers=HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    seen = {}
    for link in soup.select('a[href^="/c/"]'):
        href = link.get('href')
        text = link.get_text(strip=True)
        if href and text and CATEGORY_LINK_RE.match(href):
            seen[href.lstrip('/').split('/')[-1]] = text
    return sorted(seen.items())


def extract_video_blocks(soup):
    """Each video on a /c/<category>/<page> listing page is one
    div.thumb-block[data-eid] - data-eid is xvideos' embed id, data-id is
    its numeric video id."""
    return soup.select('div.thumb-block[data-eid]')


def parse_video_block(block):
    eid = block.get('data-eid')
    numeric_id = block.get('data-id')
    title_link = block.select_one('p.title a')
    img = block.select_one('img')

    if not eid or not numeric_id or not title_link:
        return None

    title = (title_link.get('title') or title_link.get_text()).strip()
    title = re.sub(r'\s+', ' ', title)
    if not title:
        return None

    href = title_link.get('href')
    canonical_url = urljoin(BASE_URL, href) if href else ''

    thumbnail = ''
    preview = ''
    if img:
        thumbnail = img.get('data-src') or img.get('src') or ''
        preview = img.get('data-pvv') or ''  # short hover-preview clip, same as pornhub/xvideos scrubbing

    return {
        'wp_id': int(numeric_id),
        'title': title,
        'canonical_url': canonical_url,
        'thumbnail': thumbnail,
        'preview': preview,
        'embed_url': f'{BASE_URL}/embedframe/{eid}',
    }


class Command(BaseCommand):
    help = 'Scrape video listings from a xvideos.com category page and add them to the database'

    def add_arguments(self, parser):
        parser.add_argument(
            'category', type=str, nargs='?', default=None,
            help='Category slug as it appears in the URL, e.g. Big_Ass-24. '
                 'Omit to scrape every listed category.'
        )
        parser.add_argument('startpage', type=int, nargs='?', default=0, help='Page to start from (0 = first page)')
        parser.add_argument('endpage', type=int, nargs='?', default=None,
                             help='Page to stop at (inclusive). Omit to go until a page has no videos.')
        parser.add_argument(
            '--list-categories', action='store_true',
            help='Print every available category slug and exit without scraping.'
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Stop after this many NEW videos are created (across all categories/pages in this run). '
                 'Videos already in the database don\'t count against the limit.'
        )

    def handle(self, *args, **options):
        scraper = cloudscraper.create_scraper()

        if options['list_categories']:
            print("🔎 Fetching category list from xvideos.com...")
            for slug, name in fetch_all_categories(scraper):
                print(f"  {slug:<30} {name}")
            return

        category_slug = options['category']
        startpage = options['startpage']
        endpage = options['endpage']
        self.limit = options['limit']
        self.created_count = 0

        if category_slug:
            self.scrape_category(scraper, category_slug, startpage, endpage)
            print(f"\n✅ Done. {self.created_count} new video(s) created.")
            return

        print("🔎 No category given - discovering all categories to scrape everything...")
        categories = fetch_all_categories(scraper)
        print(f"📋 Found {len(categories)} categories.")

        for slug, name in categories:
            if self.limit is not None and self.created_count >= self.limit:
                break
            print(f"\n===== 📂 Category: {name} ({slug}) =====")
            self.scrape_category(scraper, slug, startpage, endpage, category_name=name)
            time.sleep(2)  # be polite between categories

        print(f"\n✅ Done. {self.created_count} new video(s) created.")

    def scrape_category(self, scraper, category_slug, startpage, endpage, category_name=None):
        # Use the accurate name discovered from xvideos' own nav when available
        # (e.g. 'Black' for Black_Woman-30) rather than a generic derivation
        # from the slug (which would produce the clunkier 'Black Woman').
        category_name = category_name or category_display_name(category_slug)
        category, _ = Category.objects.get_or_create(
            name=category_name,
            defaults={'slug': slugify(category_name)}
        )

        base_url = f'{BASE_URL}/c/{category_slug}'

        page = startpage
        consecutive_errors = 0
        max_consecutive_errors = 5

        while True:
            if endpage is not None and page > endpage:
                print("✅ Reached end page limit.")
                break

            if self.limit is not None and self.created_count >= self.limit:
                print(f"✅ Reached limit of {self.limit} new videos.")
                break

            url = base_url if page == 0 else f'{base_url}/{page}'

            try:
                print(f"\n🌐 Fetching {category_name} page {page}...")
                response = scraper.get(url, headers=HEADERS, timeout=15)
                response.raise_for_status()
            except Exception as e:
                print(f"🔥 Request failed: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print(f"❌ Too many consecutive errors ({consecutive_errors}). Stopping category.")
                    return
                time.sleep(5)
                continue

            consecutive_errors = 0
            soup = BeautifulSoup(response.text, 'html.parser')
            blocks = extract_video_blocks(soup)

            if not blocks:
                print("✅ No more videos found. Finished category.")
                break

            for block in blocks:
                if self.limit is not None and self.created_count >= self.limit:
                    break
                try:
                    self.process_block(block, category)
                except Exception as e:
                    print(f"💥 Error processing video: {e}")
                    continue

            page += 1
            time.sleep(1.5)  # be polite between page requests

    def process_block(self, block, category):
        data = parse_video_block(block)
        if not data:
            return

        print(f"\n🎬 Processing: {data['title']} (ID: {data['wp_id']})")

        slug = slugify(f"{data['title']}-{data['wp_id']}")[:500]
        now = timezone.now()

        movie, created = Movie.objects.get_or_create(
            wp_id=data['wp_id'],
            defaults={
                'title': data['title'],
                'slug': slug,
                'date': now,
                'date_gmt': now,
                'modified': now,
                'modified_gmt': now,
                'status': 'publish',
                'post_type': 'post',
                'image_url': data['thumbnail'],
                'canonical_url': data['canonical_url'],
                'video_sources': [{
                    'url': data['embed_url'],
                    'type': 'iframe',
                    'label': 'Source 1',
                    'preview': data['preview'],
                }],
                'download_links': [],
                'author_id': 1,
                'scraped': True,
            }
        )

        movie.categories.add(category)

        if created:
            self.created_count += 1
            print(f"✅ Created new movie: {data['title']}")
        else:
            print(f"ℹ️ Already exists: {data['title']}")
