import datetime

import pytest
from django.urls import reverse

from tracker import stats
from tracker.models import ResumeVersion, Stage

pytestmark = pytest.mark.django_db


@pytest.fixture
def search(user, make_application):
    """
    Six applications with known histories:
      saved          never applied (doesn't count)
      ghosted        Applied, no reply
      oa_rejected    Applied → OA → Rejected
      interview      Applied → OA → Interview
      offer          Applied → Interview → Offer
      straight_no    added directly as Rejected (counts as applied + response)
    """
    v1 = ResumeVersion.objects.create(user=user, name="v1")
    v2 = ResumeVersion.objects.create(user=user, name="v2")
    paths = {
        "saved": [],
        "ghosted": [Stage.APPLIED],
        "oa_rejected": [Stage.APPLIED, Stage.ONLINE_ASSESSMENT, Stage.REJECTED],
        "interview": [Stage.APPLIED, Stage.ONLINE_ASSESSMENT, Stage.INTERVIEW],
        "offer": [Stage.APPLIED, Stage.INTERVIEW, Stage.OFFER],
    }
    resumes = {"ghosted": v1, "oa_rejected": v1, "interview": v2, "offer": v2}
    for name, path in paths.items():
        application = make_application(user, company=name, resume_version=resumes.get(name))
        for stage in path:
            application.move_to(stage)
    make_application(user, company="straight_no", stage=Stage.REJECTED)


def test_summary(user, search):
    summary = stats.summary(user)

    assert summary["total"] == 6
    assert summary["applied"] == 5
    assert summary["responded"] == 4  # everyone but "ghosted"
    assert summary["response_rate"] == 80
    assert summary["interviews"] == 2
    assert summary["offers"] == 1
    assert summary["rejected"] == 2


def test_funnel_counts_the_furthest_stage_reached(user, search):
    funnel = {step["stage"]: (step["count"], step["percent"]) for step in stats.summary(user)["funnel"]}

    assert funnel == {
        Stage.APPLIED: (5, 100),
        Stage.ONLINE_ASSESSMENT: (
            3,
            60,
        ),  # oa_rejected (before rejection), interview, offer (skipped OA but went further)
        Stage.INTERVIEW: (2, 40),
        Stage.OFFER: (1, 20),
    }


def test_response_rate_per_resume_version(user, search):
    rows = {row["name"]: (row["applied"], row["responded"], row["rate"]) for row in stats.per_resume(user)}

    assert rows == {
        "v1": (2, 1, 50),
        "v2": (2, 2, 100),
        None: (1, 1, 100),  # straight_no has no resume version
    }


def test_per_week_fills_empty_weeks(user, make_application):
    today = datetime.date(2026, 10, 14)  # a Wednesday
    make_application(user, stage=Stage.APPLIED, date_applied=datetime.date(2026, 10, 12))
    make_application(user, stage=Stage.APPLIED, date_applied=datetime.date(2026, 10, 13))
    make_application(user, stage=Stage.APPLIED, date_applied=datetime.date(2026, 9, 30))
    make_application(user, stage=Stage.APPLIED, date_applied=datetime.date(2025, 1, 1))  # too old

    weeks = stats.per_week(user, today=today)

    assert len(weeks) == stats.WEEKS_SHOWN
    assert weeks[-1] == {"week": datetime.date(2026, 10, 12), "count": 2}
    assert weeks[-3] == {"week": datetime.date(2026, 9, 28), "count": 1}
    assert sum(w["count"] for w in weeks) == 3


def test_no_division_by_zero_without_applications(user):
    summary = stats.summary(user)
    assert summary["response_rate"] is None
    assert stats.per_resume(user) == []


def test_stats_ignore_other_users(user, other_user, make_application):
    make_application(other_user, stage=Stage.OFFER)

    assert stats.summary(user)["applied"] == 0
    assert all(week["count"] == 0 for week in stats.per_week(user))


def test_stats_page(client, user, search, django_assert_max_num_queries):
    client.force_login(user)

    # session + user + summary + per week + per resume: a fixed number, however much data.
    with django_assert_max_num_queries(5):
        response = client.get(reverse("tracker:stats"))

    content = response.content.decode()
    assert "80%" in content
    assert "4 of 5 applications heard back" in content


def test_stats_page_empty_state(client, user):
    client.force_login(user)
    assert "No stats yet" in client.get(reverse("tracker:stats")).content.decode()
