from django.conf import settings


def site_settings(request):
    return {
        'TELEGRAM_CHANNEL_INVITE_LINK': settings.TELEGRAM_CHANNEL_INVITE_LINK,
    }
