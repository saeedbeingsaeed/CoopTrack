import datetime
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.core import mail, signing
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from tracker import reminders
from tracker.models import Application, Stage

pytestmark = pytest.mark.django_db


def verify(user):
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)


@pytest.fixture(autouse=True)
def verified_users(user, other_user):
    """Reminders only go to verified addresses; these tests are about everything else."""
    verify(user)
    verify(other_user)


TODAY = datetime.date(2026, 10, 12)


def days(n):
    return TODAY + datetime.timedelta(days=n)


def make_stale(application, days_ago):
    Application.objects.filter(pk=application.pk).update(updated_at=timezone.now() - datetime.timedelta(days=days_ago))


def digest_for(user):
    [digest] = [d for d in reminders.build_digests([user], TODAY) if d.user == user] or [None]
    return digest


# --- What goes in the email --------------------------------------------------------


def test_deadlines_in_the_next_three_days_are_included(user, make_application):
    for offset, company in [(-1, "Yesterday"), (0, "Today"), (3, "In3"), (4, "In4")]:
        make_application(user, company=company, deadline=days(offset))

    digest = digest_for(user)

    assert [a.company for a in digest.deadlines] == ["Today", "In3"]


def test_closed_applications_are_left_out(user, make_application):
    make_application(user, company="Offer", stage=Stage.OFFER, deadline=days(1))
    make_application(user, company="Rejected", stage=Stage.REJECTED, deadline=days(1))
    make_stale(make_application(user, company="OldRejected", stage=Stage.REJECTED), 30)

    assert digest_for(user) is None


def test_applications_with_no_update_in_two_weeks_are_included(user, make_application):
    make_stale(make_application(user, company="Old", stage=Stage.APPLIED), 15)
    make_stale(make_application(user, company="Recent", stage=Stage.APPLIED), 13)

    digest = digest_for(user)

    assert [a.company for a in digest.stale] == ["Old"]
    assert digest.subject == "1 to follow up on"


def test_subject_summarises_both_lists(user, make_application):
    make_application(user, deadline=days(1))
    make_application(user, deadline=days(2))
    make_stale(make_application(user, company="Old"), 20)

    assert digest_for(user).subject == "2 deadlines coming up and 1 to follow up on"


def test_each_email_only_contains_its_own_users_applications(user, other_user, make_application):
    make_application(user, company="Mine", deadline=days(1))
    make_application(other_user, company="Theirs", deadline=days(1))

    digests = {d.user: [a.company for a in d.deadlines] for d in reminders.build_digests([user, other_user], TODAY)}

    assert digests == {user: ["Mine"], other_user: ["Theirs"]}


def test_building_digests_takes_two_queries_for_any_number_of_users(
    django_user_model, make_application, django_assert_num_queries
):
    users = [django_user_model.objects.create_user(email=f"u{i}@example.com") for i in range(10)]
    for u in users:
        verify(u)
        make_application(u, deadline=days(1))
        make_stale(make_application(u), 20)

    with django_assert_num_queries(2):
        reminders.build_digests(users, TODAY)


@pytest.mark.parametrize(
    "change",
    [{"reminders_enabled": False}, {"is_demo": True}, {"is_active": False}, {"last_reminder_sent_on": TODAY}],
)
def test_who_gets_skipped(user, change):
    for name, value in change.items():
        setattr(user, name, value)
    user.save()

    assert user not in reminders.recipients(TODAY)


# --- Sending -------------------------------------------------------------------------


def test_sends_one_email_per_user_with_html_and_unsubscribe_headers(user, other_user, make_application, settings):
    settings.SITE_URL = "https://offerboard.example"
    make_application(user, company="Shopify", deadline=days(1))
    # other_user has nothing to report, so gets nothing.

    sent, failed = reminders.send_all(TODAY)

    assert (sent, failed) == (1, 0)
    [message] = mail.outbox
    assert message.to == [user.email]
    assert "Shopify" in message.body
    html, mimetype = message.alternatives[0]
    assert mimetype == "text/html" and "Shopify" in html
    assert message.extra_headers["List-Unsubscribe"].startswith("<https://offerboard.example/unsubscribe/")
    assert message.extra_headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_running_twice_on_the_same_day_sends_once(user, make_application):
    make_application(user, deadline=days(1))

    reminders.send_all(TODAY)
    reminders.send_all(TODAY)
    user.refresh_from_db()

    assert len(mail.outbox) == 1
    assert user.last_reminder_sent_on == TODAY


def test_one_failure_does_not_stop_the_others(user, other_user, make_application):
    make_application(user, deadline=days(1))
    make_application(other_user, deadline=days(1))
    real_send = mail.backends.locmem.EmailBackend.send_messages

    def flaky(self, messages):
        if messages[0].to == [user.email]:
            raise ConnectionError("SMTP said no")
        return real_send(self, messages)

    with mock.patch.object(mail.backends.locmem.EmailBackend, "send_messages", flaky):
        sent, failed = reminders.send_all(TODAY)

    assert (sent, failed) == (1, 1)
    assert [m.to for m in mail.outbox] == [[other_user.email]]
    user.refresh_from_db()
    assert user.last_reminder_sent_on is None  # will be retried on the next run


def test_command_dry_run_sends_nothing(user, make_application, capsys):
    make_application(user, deadline=timezone.localdate() + datetime.timedelta(days=1))

    call_command("send_reminders", "--dry-run")

    assert mail.outbox == []
    assert f"Would email {user.email}" in capsys.readouterr().out


def test_command_fails_loudly_when_an_email_fails(user, make_application):
    make_application(user, deadline=days(1))
    failing = mock.patch.object(mail.backends.locmem.EmailBackend, "send_messages", side_effect=ConnectionError)
    with failing, pytest.raises(CommandError, match="1 email failed"):
        call_command("send_reminders", "--date", TODAY.isoformat())


# --- Unsubscribe -----------------------------------------------------------------------


def unsubscribe_path(user):
    return reverse("unsubscribe", args=[reminders.unsubscribe_url(user).rsplit("/", 2)[-2]])


def test_unsubscribe_link_asks_first_then_turns_reminders_off(client, user):
    url = unsubscribe_path(user)

    assert "Turn off email reminders?" in client.get(url).content.decode()
    user.refresh_from_db()
    assert user.reminders_enabled  # opening the link alone changes nothing

    client.post(url)
    user.refresh_from_db()
    assert not user.reminders_enabled


def test_one_click_unsubscribe_works_without_a_session_or_csrf_token(user):
    """Mail apps POST to the List-Unsubscribe URL with no cookies (RFC 8058)."""
    response = Client(enforce_csrf_checks=True).post(unsubscribe_path(user), {"List-Unsubscribe": "One-Click"})

    assert response.status_code == 200
    user.refresh_from_db()
    assert not user.reminders_enabled


def test_tampered_unsubscribe_tokens_are_rejected(client, user, other_user):
    token = reminders.unsubscribe_url(user).rsplit("/", 2)[-2]
    value, signature = token.rsplit(":", 1)
    bad_signature = f"{value}:{signature[::-1]}"
    signed_elsewhere = signing.dumps(other_user.pk, key="not-our-secret-key", salt=reminders.UNSUBSCRIBE_SALT)

    for forged in [bad_signature, signed_elsewhere, "nonsense"]:
        assert client.post(reverse("unsubscribe", args=[forged])).status_code == 404
    user.refresh_from_db()
    other_user.refresh_from_db()
    assert user.reminders_enabled and other_user.reminders_enabled


# --- Settings and preview ------------------------------------------------------------------


def test_settings_toggle(client, user):
    client.force_login(user)

    response = client.post(reverse("settings"), {}, HTTP_HX_REQUEST="true")  # unchecked box = off

    assert response.status_code == 204
    assert "turned off" in response["HX-Trigger"]
    user.refresh_from_db()
    assert not user.reminders_enabled

    client.post(reverse("settings"), {"reminders_enabled": "on"})
    user.refresh_from_db()
    assert user.reminders_enabled


def test_preview_shows_my_email_only(client, user, other_user, make_application):
    make_application(user, company="Mine", deadline=timezone.localdate())
    make_application(other_user, company="Theirs", deadline=timezone.localdate())
    client.force_login(user)

    content = client.get(reverse("reminder_preview")).content.decode()

    assert "Mine" in content
    assert "Theirs" not in content


def test_preview_with_nothing_to_send(client, user):
    client.force_login(user)
    assert "No email today" in client.get(reverse("reminder_preview")).content.decode()


def test_password_reset_page_is_honest_when_email_is_off(client, settings):
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}}  # as on Render
    content = client.get(reverse("account_reset_password")).content.decode()
    assert "isn't available yet" in content
    assert "Send reset link" not in content


# --- Only verified addresses -------------------------------------------------------------


def test_unverified_addresses_get_no_reminders(django_user_model, make_application):
    """Stops someone signing up with another person's address and having emails sent to them."""
    stranger = django_user_model.objects.create_user(email="someone-else@example.com", password="x")
    EmailAddress.objects.create(user=stranger, email=stranger.email, verified=False)
    make_application(stranger, deadline=days(1))

    assert stranger not in reminders.recipients(TODAY)
    assert not reminders.has_verified_email(stranger)


def test_signing_in_with_google_verifies_an_existing_account(django_user_model, rf):
    from allauth.socialaccount.models import SocialAccount, SocialLogin
    from allauth.socialaccount.signals import social_account_added

    member = django_user_model.objects.create_user(email="Ada@Example.com", password="x")
    EmailAddress.objects.create(user=member, email=member.email, verified=False)
    login = SocialLogin(
        user=member,
        account=SocialAccount(provider="google", uid="123"),
        email_addresses=[EmailAddress(email="ada@example.com", verified=True, primary=True)],
    )

    social_account_added.send(sender=SocialLogin, request=rf.get("/"), sociallogin=login)

    assert reminders.has_verified_email(member)


def test_settings_page_explains_how_to_get_reminders(client, django_user_model, settings):
    settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET = "id", "secret"
    settings.SOCIALACCOUNT_PROVIDERS = {"google": {"APPS": [{"client_id": "id", "secret": "secret", "key": ""}]}}
    member = django_user_model.objects.create_user(email="new@example.com", password="x")
    client.force_login(member)

    content = client.get(reverse("settings")).content.decode()

    assert "Reminders aren't being sent yet" in content
    assert "Verify with Google" in content
    assert "process=connect" in content


def test_verified_users_see_no_warning(client, user):
    client.force_login(user)  # verified by the autouse fixture
    assert "Reminders aren't being sent yet" not in client.get(reverse("settings")).content.decode()
