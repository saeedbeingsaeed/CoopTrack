import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts import demo, metrics
from accounts.models import User
from tracker.models import Application, Stage

pytestmark = pytest.mark.django_db


def test_only_staff_can_see_metrics(client, user):
    client.force_login(user)
    assert client.get(reverse("metrics")).status_code == 302  # sent to the admin login

    user.is_staff = True
    user.save()
    assert client.get(reverse("metrics")).status_code == 200


def test_anonymous_visitors_cannot_see_metrics(client):
    assert client.get(reverse("metrics")).status_code == 302


def test_counts_signups_and_active_users_without_demo_accounts(user, other_user, make_application):
    now = timezone.now()
    User.objects.filter(pk=other_user.pk).update(
        date_joined=now - datetime.timedelta(days=70)
    )  # before the 8-week chart
    make_application(user, stage=Stage.APPLIED)  # user is active now; other_user did nothing
    stale = make_application(other_user)
    Application.objects.filter(pk=stale.pk).update(updated_at=now - datetime.timedelta(days=20))
    stale.history.update(changed_at=now - datetime.timedelta(days=20))
    demo.create_demo_user()

    m = metrics.collect(now)

    assert m["signups"] == 2
    assert m["signups_7d"] == 1
    assert m["signups_30d"] == 1
    assert m["active_7d"] == 1
    assert m["active_30d"] == 2
    assert m["demos_7d"] == 1
    assert m["applications"] == 2  # demo applications not counted
    assert sum(week["count"] for week in m["weekly"]) == 1


def test_metrics_page_query_count(client, user, django_assert_max_num_queries):
    user.is_staff = True
    user.save()
    client.force_login(user)
    with django_assert_max_num_queries(7):
        client.get(reverse("metrics"))
