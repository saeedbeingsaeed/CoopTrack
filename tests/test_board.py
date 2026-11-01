import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from tracker.models import Stage, StageChange

pytestmark = pytest.mark.django_db

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


def columns(response):
    return {stage: [a.company for a in apps] for stage, apps in response.context["columns"]}


def test_board_is_the_home_page_after_sign_in(client, user):
    response = client.post(reverse("account_login"), {"login": user.email, "password": "correct-horse-1"})
    assert response.url == reverse("tracker:board")


def test_board_groups_applications_into_all_six_columns(signed_in, user, make_application):
    make_application(user, company="Shopify", stage=Stage.APPLIED)
    make_application(user, company="RBC", stage=Stage.INTERVIEW)

    cols = columns(signed_in.get(reverse("tracker:board")))

    assert list(cols) == list(Stage)
    assert cols[Stage.APPLIED] == ["Shopify"]
    assert cols[Stage.INTERVIEW] == ["RBC"]
    assert cols[Stage.OFFER] == []


def test_cards_are_ordered_by_deadline_with_no_deadline_last(signed_in, user, make_application):
    make_application(user, company="None")
    make_application(user, company="Later", deadline=datetime.date(2026, 12, 1))
    make_application(user, company="Sooner", deadline=datetime.date(2026, 11, 1))

    assert columns(signed_in.get(reverse("tracker:board")))[Stage.SAVED] == ["Sooner", "Later", "None"]


def test_cards_know_when_they_entered_their_stage(signed_in, user, make_application):
    application = make_application(user)
    application.move_to(Stage.APPLIED)
    entered = timezone.now() - datetime.timedelta(days=5)
    application.history.filter(to_stage=Stage.APPLIED).update(changed_at=entered)

    response = signed_in.get(reverse("tracker:board"))

    [card] = [a for _, apps in response.context["columns"] for a in apps]
    assert card.stage_since == entered


def test_board_only_shows_my_applications(signed_in, user, other_user, make_application):
    make_application(user, company="Mine")
    make_application(other_user, company="Theirs")

    content = signed_in.get(reverse("tracker:board")).content.decode()

    assert "Mine" in content
    assert "Theirs" not in content


def test_empty_board_shows_the_welcome_state(signed_in):
    content = signed_in.get(reverse("tracker:board")).content.decode()
    assert "Your board is empty" in content


def test_htmx_refresh_returns_just_the_board(signed_in, user, make_application):
    make_application(user)

    content = signed_in.get(reverse("tracker:board"), **HTMX).content.decode()

    assert content.lstrip().startswith('<div id="board"')
    assert "<html" not in content


def test_cards_have_a_move_menu_for_keyboard_users(signed_in, user, make_application):
    application = make_application(user, stage=Stage.APPLIED)

    content = signed_in.get(reverse("tracker:board")).content.decode()

    assert f'id="move-{application.pk}"' in content
    assert f'aria-label="Move {application.company}"' in content
    # The menu offers every stage except the current one.
    assert content.count('name="to" value=') == len(Stage) - 1


def test_board_query_count_does_not_grow_with_cards(signed_in, user, make_application, django_assert_max_num_queries):
    for i in range(40):
        application = make_application(user, company=f"C{i}", stage=i % len(Stage))
        application.move_to((i + 1) % len(Stage))

    # session + user + one query for every card (with its stage_since).
    with django_assert_max_num_queries(3):
        signed_in.get(reverse("tracker:board"))


def test_detail_timeline_shows_time_spent_in_each_stage(signed_in, user, make_application):
    application = make_application(user)
    start = timezone.now() - datetime.timedelta(days=10)
    application.history.update(changed_at=start)
    StageChange.objects.create(
        application=application,
        from_stage=Stage.SAVED,
        to_stage=Stage.APPLIED,
        changed_at=start + datetime.timedelta(days=3),
    )

    response = signed_in.get(reverse("tracker:detail", args=[application.pk]))
    content = response.content.decode()

    assert "3\xa0days in Saved" in content
    assert "In Applied for 1\xa0week" in content
    newest_first = [change.to_stage for change, _ in response.context["timeline"]]
    assert newest_first == [Stage.APPLIED, Stage.SAVED]
