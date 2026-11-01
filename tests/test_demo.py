import datetime

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts import demo
from accounts.models import User
from tracker import reminders
from tracker.models import Application, ResumeVersion, Stage, StageChange

pytestmark = pytest.mark.django_db


def test_try_the_demo_signs_in_a_new_demo_user_with_sample_data(client):
    response = client.post(reverse("demo"))

    assert response.url == reverse("tracker:board")
    user = User.objects.get()
    assert user.is_demo
    assert not user.has_usable_password()
    assert user.email.endswith("@demo.invalid")
    assert client.get(reverse("tracker:board")).context["user"] == user
    assert Application.objects.filter(user=user).count() == len(demo.SAMPLE)


def test_demo_data_covers_every_stage_and_has_history(client):
    client.post(reverse("demo"))
    user = User.objects.get()

    stages = set(Application.objects.filter(user=user).values_list("stage", flat=True))
    assert stages == set(Stage)
    # Every application has history ending in its current stage.
    for application in Application.objects.filter(user=user):
        assert application.history.order_by("changed_at").last().to_stage == application.stage


def test_demo_needs_a_post(client):
    assert client.get(reverse("demo")).status_code == 405
    assert not User.objects.exists()


def test_each_visitor_gets_their_own_demo(client, django_user_model):
    from django.test import Client

    client.post(reverse("demo"))
    Client().post(reverse("demo"))

    assert django_user_model.objects.filter(is_demo=True).count() == 2


def test_demo_never_touches_real_users_data(client, user, make_application):
    mine = make_application(user, company="Real Co", notes="private")
    ResumeVersion.objects.create(user=user, name="SWE v3")  # same name as a demo resume
    before = (Application.objects.filter(user=user).count(), StageChange.objects.filter(application=mine).count())

    client.post(reverse("demo"))
    board = client.get(reverse("tracker:board")).content.decode()
    table = client.get(reverse("tracker:table"), {"q": "Real"}).content.decode()

    assert "Real Co" not in board + table
    assert (
        Application.objects.filter(user=user).count(),
        StageChange.objects.filter(application=mine).count(),
    ) == before
    assert ResumeVersion.objects.filter(user=user).count() == 1
    assert client.get(reverse("tracker:detail", args=[mine.pk])).status_code == 404


def test_signed_in_users_are_not_swapped_for_a_demo(client, user):
    client.force_login(user)

    client.post(reverse("demo"))

    assert not User.objects.filter(is_demo=True).exists()
    assert client.get(reverse("tracker:board")).context["user"] == user


def test_signing_out_deletes_the_demo_account(client):
    client.post(reverse("demo"))

    client.post(reverse("account_logout"))

    assert not User.objects.exists()
    assert not Application.objects.exists()


def test_demo_banner_offers_a_real_account(client):
    client.post(reverse("demo"))
    content = client.get(reverse("tracker:board")).content.decode()
    assert "exploring a demo" in content
    assert f'name="next" value="{reverse("account_signup")}"' in content


def test_purge_deletes_only_expired_demo_users(user, make_application):
    old_demo = demo.create_demo_user()
    new_demo = demo.create_demo_user()
    make_application(user)
    a_day_ago = timezone.now() - datetime.timedelta(hours=25)
    User.objects.filter(pk__in=[old_demo.pk, user.pk]).update(date_joined=a_day_ago)  # real user is old too

    call_command("purge_demo_users")

    assert set(User.objects.values_list("pk", flat=True)) == {user.pk, new_demo.pk}
    assert Application.objects.filter(user=user).count() == 1


def test_demo_users_get_no_reminder_emails():
    demo_user = demo.create_demo_user()
    assert demo_user not in reminders.recipients(timezone.localdate())


def test_creating_a_demo_takes_a_fixed_number_of_queries(django_assert_max_num_queries):
    with django_assert_max_num_queries(12):
        demo.create_demo_user()


def test_landing_page_has_the_demo_button(client):
    content = client.get(reverse("landing")).content.decode()
    assert f'action="{reverse("demo")}"' in content
    assert "Try the demo" in content
