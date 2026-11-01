import datetime
import json

import pytest
from django.test import Client
from django.urls import reverse

from tracker.models import Application, ResumeVersion, Stage

pytestmark = pytest.mark.django_db

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


# --- Create / edit / delete ---------------------------------------------------------


def test_add_an_application(signed_in, user):
    response = signed_in.post(
        reverse("tracker:create"),
        {
            "company": "Shopify",
            "role": "Backend Intern",
            "stage": Stage.APPLIED,
            "deadline": "2026-11-01",
            "posting_url": "https://shopify.com/careers/1",
            "notes": "Referral from Priya",
        },
    )

    application = Application.objects.get(user=user)
    assert response.url == reverse("tracker:detail", args=[application.pk])
    assert application.deadline == datetime.date(2026, 11, 1)
    assert application.date_applied is not None  # applied → defaults to today
    assert application.history.get().to_stage == Stage.APPLIED


def test_add_requires_company_and_role(signed_in, user):
    response = signed_in.post(reverse("tracker:create"), {"stage": Stage.SAVED})

    assert set(response.context["form"].errors) == {"company", "role"}
    assert not Application.objects.exists()


def test_add_rejects_a_bad_link(signed_in):
    response = signed_in.post(
        reverse("tracker:create"), {"company": "A", "role": "B", "stage": 0, "posting_url": "not a url"}
    )
    assert "posting_url" in response.context["form"].errors


def test_stage_can_be_preselected(signed_in):
    response = signed_in.get(reverse("tracker:create"), {"stage": Stage.APPLIED})
    assert response.context["form"].initial["stage"] == Stage.APPLIED


def test_adding_a_new_resume_version_from_the_form(signed_in, user):
    signed_in.post(reverse("tracker:create"), {"company": "A", "role": "B", "stage": 0, "new_resume": "SWE v3"})

    application = Application.objects.get(user=user)
    assert application.resume_version.name == "SWE v3"


def test_new_resume_reuses_an_existing_name(signed_in, user):
    existing = ResumeVersion.objects.create(user=user, name="SWE v3")

    signed_in.post(reverse("tracker:create"), {"company": "A", "role": "B", "stage": 0, "new_resume": "swe V3"})

    assert Application.objects.get(user=user).resume_version == existing
    assert ResumeVersion.objects.count() == 1


def test_editing_the_stage_records_history(signed_in, user, make_application):
    application = make_application(user)

    signed_in.post(
        reverse("tracker:edit", args=[application.pk]),
        {"company": application.company, "role": application.role, "stage": Stage.INTERVIEW},
    )

    assert [c.to_stage for c in application.history.all()] == [Stage.SAVED, Stage.INTERVIEW]


def test_delete_an_application(signed_in, user, make_application):
    application = make_application(user)

    response = signed_in.post(reverse("tracker:delete", args=[application.pk]))

    assert response.url == reverse("tracker:board")
    assert not Application.objects.exists()


def test_detail_shows_history(signed_in, user, make_application):
    application = make_application(user)
    application.move_to(Stage.APPLIED)

    content = signed_in.get(reverse("tracker:detail", args=[application.pk])).content.decode()

    assert "Added as Saved" in content
    assert "Moved to Applied" in content


# --- Stage endpoint -------------------------------------------------------------------


def test_move_with_htmx_returns_events(signed_in, user, make_application):
    application = make_application(user)

    response = signed_in.post(reverse("tracker:stage", args=[application.pk]), {"to": Stage.OFFER}, **HTMX)

    assert response.status_code == 204
    events = json.loads(response["HX-Trigger"])
    assert "applications-changed" in events
    assert events["toast"]["message"] == "Shopify moved to Offer."
    application.refresh_from_db()
    assert application.stage == Stage.OFFER


def test_move_without_javascript_redirects(signed_in, user, make_application):
    application = make_application(user)

    response = signed_in.post(reverse("tracker:stage", args=[application.pk]), {"to": Stage.APPLIED})

    assert response.url == reverse("tracker:detail", args=[application.pk])


@pytest.mark.parametrize("bad", ["", "9", "-1", "offer"])
def test_move_rejects_unknown_stages(signed_in, user, make_application, bad):
    application = make_application(user)

    response = signed_in.post(reverse("tracker:stage", args=[application.pk]), {"to": bad})

    assert response.status_code == 400
    application.refresh_from_db()
    assert application.stage == Stage.SAVED


def test_move_only_accepts_post(signed_in, user, make_application):
    application = make_application(user)
    assert signed_in.get(reverse("tracker:stage", args=[application.pk])).status_code == 405


# --- Table: search, filter, sort, pages -------------------------------------------------


@pytest.fixture
def three(user, make_application):
    dec, nov = datetime.date(2026, 12, 1), datetime.date(2026, 11, 1)
    return [
        make_application(user, company="Shopify", role="Backend", stage=Stage.APPLIED, deadline=dec),
        make_application(user, company="RBC", role="Data Analyst", stage=Stage.INTERVIEW, location="Toronto"),
        make_application(user, company="Google", role="SWE", stage=Stage.APPLIED, deadline=nov),
    ]


def companies(response):
    return [a.company for a in response.context["page_obj"].object_list]


def test_search_matches_company_role_location_and_notes(signed_in, three):
    assert companies(signed_in.get(reverse("tracker:table"), {"q": "shop"})) == ["Shopify"]
    assert companies(signed_in.get(reverse("tracker:table"), {"q": "analyst"})) == ["RBC"]
    assert companies(signed_in.get(reverse("tracker:table"), {"q": "toronto"})) == ["RBC"]


def test_filter_by_stage_and_counts(signed_in, three):
    response = signed_in.get(reverse("tracker:table"), {"stage": Stage.APPLIED})

    assert sorted(companies(response)) == ["Google", "Shopify"]
    counts = {stage: n for stage, n in response.context["stage_counts"]}
    assert counts[Stage.APPLIED] == 2
    assert counts[Stage.INTERVIEW] == 1  # chips ignore the stage filter


def test_sort_by_deadline_puts_empty_deadlines_last(signed_in, three):
    response = signed_in.get(reverse("tracker:table"), {"sort": "deadline"})
    assert companies(response) == ["Google", "Shopify", "RBC"]


def test_unknown_sort_and_stage_fall_back_to_defaults(signed_in, three):
    response = signed_in.get(reverse("tracker:table"), {"sort": "password", "stage": "99"})

    assert response.status_code == 200
    assert response.context["sort"] == "updated"
    assert len(companies(response)) == 3


def test_htmx_requests_get_only_the_results(signed_in, three):
    response = signed_in.get(reverse("tracker:table"), {"q": "rbc"}, **HTMX)

    content = response.content.decode()
    assert content.lstrip().startswith('<div id="results"')
    assert "<html" not in content
    assert "RBC" in content


def test_no_matches_shows_a_message(signed_in, three):
    content = signed_in.get(reverse("tracker:table"), {"q": "zzz"}).content.decode()
    assert "No applications match" in content


def test_empty_account_shows_the_welcome_state(signed_in):
    content = signed_in.get(reverse("tracker:table")).content.decode()
    assert "Add your first application" in content


def test_pages_out_of_range_show_the_last_page(signed_in, user, make_application):
    for i in range(51):
        make_application(user, company=f"Company {i}")

    response = signed_in.get(reverse("tracker:table"), {"page": "999"})

    assert response.status_code == 200
    assert response.context["page_obj"].number == 2


# --- Query counts (N+1) ---------------------------------------------------------------


def test_table_query_count_does_not_grow_with_rows(signed_in, user, make_application, django_assert_max_num_queries):
    resume = ResumeVersion.objects.create(user=user, name="v1")
    for i in range(30):
        make_application(user, company=f"C{i}", resume_version=resume)

    # session + user + counts + exists/paginator count + rows, regardless of how many rows.
    with django_assert_max_num_queries(6):
        signed_in.get(reverse("tracker:table"))


def test_detail_query_count_does_not_grow_with_history(
    signed_in, user, make_application, django_assert_max_num_queries
):
    application = make_application(user)
    for stage in [Stage.APPLIED, Stage.ONLINE_ASSESSMENT, Stage.INTERVIEW, Stage.OFFER]:
        application.move_to(stage)

    with django_assert_max_num_queries(4):
        signed_in.get(reverse("tracker:detail", args=[application.pk]))


# --- CSRF -------------------------------------------------------------------------------


def test_htmx_posts_need_the_csrf_token(user, make_application):
    application = make_application(user)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    url = reverse("tracker:stage", args=[application.pk])

    assert client.post(url, {"to": Stage.OFFER}, **HTMX).status_code == 403

    # The page puts the token in hx-headers, so HTMX sends it as X-CSRFToken.
    client.get(reverse("tracker:table"))
    token = client.cookies["csrftoken"].value
    assert client.post(url, {"to": Stage.OFFER}, HTTP_X_CSRFTOKEN=token, **HTMX).status_code == 204


def test_pages_include_the_csrf_header_for_htmx(signed_in):
    content = signed_in.get(reverse("tracker:table")).content.decode()
    assert 'hx-headers=\'{"X-CSRFToken":' in content


# --- Resume versions --------------------------------------------------------------------


def test_add_and_delete_a_resume_version(signed_in, user, make_application):
    signed_in.post(reverse("tracker:resumes"), {"name": "SWE v1"})
    resume = ResumeVersion.objects.get(user=user)
    application = make_application(user, resume_version=resume)

    signed_in.post(reverse("tracker:resume_delete", args=[resume.pk]))

    application.refresh_from_db()
    assert application.resume_version is None  # the application stays, just untracked


def test_duplicate_resume_names_are_rejected(signed_in, user):
    ResumeVersion.objects.create(user=user, name="SWE v1")

    response = signed_in.post(reverse("tracker:resumes"), {"name": "swe v1"})

    assert "name" in response.context["form"].errors
