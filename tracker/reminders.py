"""
The daily reminder email.

Run by `python manage.py send_reminders`, which a scheduled GitHub Actions
workflow calls once a day. Each user who has reminders on gets one email listing:
- open applications with a deadline in the next 3 days, and
- open applications with no update in 2 weeks.
Nobody gets an email when there's nothing to say.

This is the one place that reads across users: it's a background job, not a
request, so there is no signed-in user to scope to. Each email is still built
only from its own recipient's rows (see build_digests and its tests).
"""

import datetime
import logging
from dataclasses import dataclass, field

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail, signing
from django.core.mail import EmailMultiAlternatives
from django.db.models import Exists, OuterRef
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Application, Stage

logger = logging.getLogger(__name__)

DEADLINE_DAYS = 3
STALE_DAYS = 14
OPEN_STAGES = [Stage.SAVED, Stage.APPLIED, Stage.ONLINE_ASSESSMENT, Stage.INTERVIEW]
UNSUBSCRIBE_SALT = "reminders.unsubscribe"


@dataclass
class Digest:
    user: object
    deadlines: list = field(default_factory=list)
    stale: list = field(default_factory=list)

    @property
    def is_empty(self):
        return not (self.deadlines or self.stale)

    @property
    def subject(self):
        parts = []
        if self.deadlines:
            parts.append(f"{len(self.deadlines)} deadline{'s' if len(self.deadlines) != 1 else ''} coming up")
        if self.stale:
            parts.append(f"{len(self.stale)} to follow up on")
        return " and ".join(parts).capitalize()


def verified_email_exists():
    """
    SQL check that a user's email address has been verified. Sign-up doesn't
    verify addresses (the web server can't send email), so without this anyone
    could register someone else's address and have reminders sent to them.
    Google sign-in verifies the address, so Google users pass.
    """
    return Exists(EmailAddress.objects.filter(user=OuterRef("pk"), email__iexact=OuterRef("email"), verified=True))


def recipients(today):
    """Users who should be considered for today's email."""
    return (
        get_user_model()
        .objects.filter(verified_email_exists(), is_active=True, is_demo=False, reminders_enabled=True)
        .exclude(last_reminder_sent_on=today)
    )


def has_verified_email(user):
    return get_user_model().objects.filter(verified_email_exists(), pk=user.pk).exists()


def build_digests(users, today):
    """
    One Digest per user that has something to report. Two queries in total,
    however many users there are, grouped by user in Python afterwards.
    """
    users = {user.pk: user for user in users}
    open_apps = Application.objects.filter(user_id__in=users, stage__in=OPEN_STAGES)
    stale_before = timezone.make_aware(
        datetime.datetime.combine(today - datetime.timedelta(days=STALE_DAYS), datetime.time.min)
    )

    digests = {}
    deadlines = open_apps.filter(deadline__range=(today, today + datetime.timedelta(days=DEADLINE_DAYS)))
    for application in deadlines.order_by("deadline", "company"):
        digests.setdefault(application.user_id, Digest(users[application.user_id])).deadlines.append(application)
    for application in open_apps.filter(updated_at__lt=stale_before).order_by("updated_at"):
        digests.setdefault(application.user_id, Digest(users[application.user_id])).stale.append(application)
    return [digest for digest in digests.values() if not digest.is_empty]


def unsubscribe_url(user):
    # A signed token instead of a login: the link works from any device, and
    # can't be forged for someone else without the SECRET_KEY.
    token = signing.dumps(user.pk, salt=UNSUBSCRIBE_SALT)
    return settings.SITE_URL + reverse("unsubscribe", args=[token])


def user_from_unsubscribe_token(token):
    """The user a token was made for, or None if the token is invalid."""
    try:
        pk = signing.loads(token, salt=UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return None
    return get_user_model().objects.filter(pk=pk).first()


def email_context(digest, today):
    return {
        "digest": digest,
        "today": today,
        "site_url": settings.SITE_URL,
        "board_url": settings.SITE_URL + reverse("tracker:board"),
        "settings_url": settings.SITE_URL + reverse("settings"),
        "unsubscribe_url": unsubscribe_url(digest.user),
        "stale_days": STALE_DAYS,
        "deadline_days": DEADLINE_DAYS,
    }


def build_message(digest, today):
    context = email_context(digest, today)
    message = EmailMultiAlternatives(
        subject=digest.subject,
        body=render_to_string("email/reminder.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[digest.user.email],
        headers={
            # Lets Gmail and others show their own "Unsubscribe" button (RFC 2369 / RFC 8058).
            "List-Unsubscribe": f"<{context['unsubscribe_url']}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )
    message.attach_alternative(render_to_string("email/reminder.html", context), "text/html")
    return message


def send_all(today, dry_run=False, stdout=None):
    """Send today's emails. Returns (sent, failed). Failures are logged, not fatal."""
    digests = build_digests(recipients(today), today)
    if dry_run:
        for digest in digests:
            print(f"Would email {digest.user.email}: {digest.subject}", file=stdout)
        return len(digests), 0

    sent = failed = 0
    with mail.mailers.default as connection:  # one SMTP connection for the whole run
        for digest in digests:
            try:
                connection.send_messages([build_message(digest, today)])
            except Exception:
                # One bad address mustn't stop everyone else's email.
                logger.exception("Reminder to user %s failed", digest.user.pk)
                failed += 1
                continue
            # Recorded per user straight away, so a re-run after a crash skips them.
            type(digest.user).objects.filter(pk=digest.user.pk).update(last_reminder_sent_on=today)
            sent += 1
    return sent, failed
