from django.conf import settings


def email_sending_enabled():
    return "console" not in settings.MAILERS["default"]["BACKEND"]


def auth_options(request):
    return {
        "google_enabled": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        "email_enabled": email_sending_enabled(),
    }
