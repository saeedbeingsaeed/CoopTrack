from django.conf import settings


def email_sending_enabled():
    """True when a real mail server is configured (not the log-only console backend)."""
    return "console" not in settings.MAILERS["default"]["BACKEND"]


def auth_options(request):
    """Lets templates hide features that aren't configured, like the Google button."""
    return {
        "google_enabled": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        "email_enabled": email_sending_enabled(),
    }
