from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from movies.models import Movie
from movies.telegram_bot import post_link, post_video, TelegramPostError

MAX_ATTEMPTS = 5


class Command(BaseCommand):
    help = (
        'Post an unposted movie to the After Dark Telegram channel. '
        'Run this from cron - 5x/day with --type link (Naija only), '
        'spread across the day (see DEPLOYMENT.md for the exact schedule).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--type', choices=['link', 'video'], required=True)

    def handle(self, *args, **options):
        post_type = options['type']
        post_fn = post_link if post_type == 'link' else post_video

        unposted = Movie.objects.filter(status='publish', telegram_posted_at__isnull=True)

        # The channel is Nigerian-only: post Naija-tagged content (from
        # `scrape_xvideos --search naija`) and nothing else. No fallback to
        # the general pool - if Naija runs out, skip the slot and scrape more.
        candidates = list(
            unposted.filter(categories__name__icontains='naija').distinct().order_by('-date')[:MAX_ATTEMPTS]
        )

        if not candidates:
            self.stdout.write('No unposted Naija movies available - run: scrape_xvideos --search naija')
            return

        for movie in candidates:
            try:
                post_fn(movie)
            except TelegramPostError as e:
                self.stdout.write(f'Skipped "{movie.title}": {e}')
                continue
            except Exception as e:
                self.stdout.write(f'Failed on "{movie.title}": {e}')
                continue

            movie.telegram_posted_at = timezone.now()
            movie.telegram_post_type = post_type
            movie.save(update_fields=['telegram_posted_at', 'telegram_post_type'])
            self.stdout.write(f'Posted ({post_type}): {movie.title}')
            return

        raise CommandError(f'Tried {len(candidates)} movies, none could be posted as "{post_type}".')
