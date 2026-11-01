# Stage rules, undo, search ranking, Find jobs, and the CLI.

import datetime
import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from tracker.adzuna import to_posting
from tracker.domain.errors import InvalidMove, NotFound, NothingToUndo
from tracker.domain.postings import JobSource, Posting, SampleJobSource
from tracker.domain.ranking import RANKINGS, get_ranking
from tracker.domain.stages import state_for
from tracker.forms import ApplicationForm
from tracker.models import Application, JobPosting, Stage, StageSnapshot, Via
from tracker.services import ApplicationService

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


def cli(user, *args):
    out = io.StringIO()
    call_command("cooptrack", "--user", user.email, *args, stdout=out)
    return out.getvalue()


# --- State --------------------------------------------------------------------------


def test_applications_only_move_forward(user, make_application):
    app = make_application(user, stage=Stage.INTERVIEW)
    with pytest.raises(InvalidMove, match="only move forward"):
        app.move_to(Stage.APPLIED)
    app.refresh_from_db()
    assert app.stage == Stage.INTERVIEW
    assert app.history.count() == 1  # nothing recorded for the refused move


def test_offer_and_rejected_are_final(user, make_application):
    for stage in (Stage.OFFER, Stage.REJECTED):
        state = state_for(stage)
        assert state.is_final
        with pytest.raises(InvalidMove, match="final stage"):
            state.move(make_application(user, stage=stage), Stage.SAVED)


def test_stages_can_be_skipped_forward_and_rejected_from_any_open_stage(user, make_application):
    assert make_application(user).move_to(Stage.INTERVIEW)
    for stage in (Stage.SAVED, Stage.APPLIED, Stage.ONLINE_ASSESSMENT, Stage.INTERVIEW):
        assert state_for(stage).can_move_to(Stage.REJECTED)


def test_past_saved_fills_in_the_applied_date(user, make_application):
    app = make_application(user, stage=Stage.INTERVIEW)
    assert app.date_applied is not None
    assert make_application(user, company="Saved").date_applied is None


# --- Memento --------------------------------------------------------------------------


def test_undo_reverses_moves_one_at_a_time(user, make_application):
    service = ApplicationService(user)
    app = make_application(user)
    service.move(app, Stage.APPLIED)
    service.move(app, Stage.REJECTED)

    assert service.undo(app).stage == Stage.APPLIED
    back = service.undo(app)
    assert back.stage == Stage.SAVED
    assert back.date_applied is None  # the whole remembered state comes back, not just the stage
    with pytest.raises(NothingToUndo):
        service.undo(app)


def test_undo_can_leave_a_final_stage(user, make_application):
    service = ApplicationService(user)
    app = make_application(user, stage=Stage.INTERVIEW)
    service.move(app, Stage.OFFER)
    assert service.undo(app).stage == Stage.INTERVIEW


def test_refused_moves_leave_nothing_to_undo(user, make_application):
    service = ApplicationService(user)
    app = make_application(user, stage=Stage.OFFER)
    with pytest.raises(InvalidMove):
        service.move(app, Stage.SAVED)
    assert not app.undo_history.can_undo()


def test_undo_history_keeps_the_last_ten(user, make_application):
    app = make_application(user)
    for _ in range(12):
        app.undo_history.push(app.create_memento())
    assert StageSnapshot.objects.filter(application=app).count() == 10


# --- Traceability ---------------------------------------------------------------------------


def test_history_records_the_interface_and_undos(user, make_application):
    app = make_application(user)
    ApplicationService(user, via=Via.CLI).move(app, Stage.APPLIED)
    ApplicationService(user, via=Via.WEB).undo(app)

    rows = [(c.from_stage, c.to_stage, c.via, c.is_undo) for c in app.history.all()]
    assert rows == [
        (None, Stage.SAVED, Via.WEB, False),
        (Stage.SAVED, Stage.APPLIED, Via.CLI, False),
        (Stage.APPLIED, Stage.SAVED, Via.WEB, True),
    ]


# --- Strategy -----------------------------------------------------------------------------


def posting(pid, title, salary=None, days_old=0, description=""):
    created = datetime.datetime(2026, 10, 30, tzinfo=datetime.UTC) - datetime.timedelta(days=days_old)
    return Posting(
        pid, title, "Acme", "Hamilton, ON", salary, salary, created, f"https://example.com/{pid}", description
    )


POSTINGS = [
    posting("a", "Senior Python Developer", salary=120000, days_old=5),
    posting("b", "Software Developer Co-op", salary=50000, days_old=9, description="python django"),
    posting("c", "Data Analyst", days_old=1, description="python"),
]


@pytest.mark.parametrize(
    "key, expected",
    [("newest", ["c", "a", "b"]), ("pay", ["a", "b", "c"]), ("student", ["b", "c", "a"]), ("match", ["a", "b", "c"])],
)
def test_each_ranking_strategy(key, expected):
    assert [p.id for p in get_ranking(key).rank(POSTINGS, "python developer")] == expected


def test_strategies_never_drop_postings():
    for strategy in RANKINGS.values():
        assert sorted(p.id for p in strategy.rank(POSTINGS, "x")) == ["a", "b", "c"]


# --- Job search and saving postings -----------------------------------------------------------


class FakeJobSource(JobSource):
    def search(self, keywords, location, limit):
        return POSTINGS[:limit]


def test_search_caches_postings_and_save_adds_them_to_the_board_once(user):
    service = ApplicationService(user, job_source=FakeJobSource())
    results = service.search_jobs("python", ranking="pay")
    assert [p.id for p in results.postings] == ["a", "b", "c"]
    assert JobPosting.objects.count() == 3

    application, created = service.save_posting("b")
    assert created and application.stage == Stage.SAVED
    assert (application.company, application.role, application.pay) == (
        "Acme",
        "Software Developer Co-op",
        "$50,000/yr",
    )
    assert service.save_posting("b") == (application, False)
    with pytest.raises(NotFound):
        service.save_posting("missing")


def test_find_jobs_page_uses_sample_postings_without_adzuna_keys(signed_in, settings):
    settings.ADZUNA_APP_ID = settings.ADZUNA_APP_KEY = ""
    response = signed_in.get(reverse("tracker:jobs"), {"q": "developer", "rank": "student"})
    content = response.content.decode()
    assert response.status_code == 200
    assert "Sample postings" in content
    assert content.index("Software Developer Co-op") < content.index("Junior Backend Developer")


def test_saving_a_posting_from_the_page(signed_in, user, settings):
    settings.ADZUNA_APP_ID = ""
    signed_in.get(reverse("tracker:jobs"), {"q": "developer"})
    posting_id = SampleJobSource().search("", "", 1)[0].id

    response = signed_in.post(reverse("tracker:save_posting", args=[posting_id]), **HTMX)
    assert response.status_code == 200
    assert "On your board" in response.content.decode()
    assert Application.objects.for_user(user).get().company == "Northwind Software"


def test_adzuna_repeats_a_search_from_the_cache(monkeypatch):
    from django.core.cache import cache

    from tracker import adzuna

    cache.clear()
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(url, timeout):
        calls.append(url)
        return Response(b'{"results": [{"id": 7, "title": "Developer Co-op"}]}')

    monkeypatch.setattr(adzuna.urllib.request, "urlopen", fake_urlopen)
    source = adzuna.AdzunaJobSource("id", "key")
    assert source.search("python", "", 20)[0].id == "adzuna-7"
    assert source.search("Python", "", 20)[0].id == "adzuna-7"  # same search, any case: no second call
    assert len(calls) == 1


def test_adzuna_result_parsing():
    p = to_posting({
        "id": 4123, "title": "Junior <strong>Developer</strong>", "company": {"display_name": "Acme"},
        "location": {"display_name": "Hamilton, Ontario"}, "salary_min": 50000, "salary_max": 60000,
        "created": "2026-10-20T14:03:11Z", "redirect_url": "https://adzuna.ca/x", "description": "Build things",
    })  # fmt: skip
    assert (p.id, p.title, p.company, p.pay) == ("adzuna-4123", "Junior Developer", "Acme", "$50,000–$60,000/yr")
    assert to_posting({"id": 1}).created is None


# --- Website ----------------------------------------------------------------------------------


def test_refused_move_returns_409_with_the_reason(signed_in, user, make_application):
    app = make_application(user, stage=Stage.REJECTED)
    response = signed_in.post(reverse("tracker:stage", args=[app.pk]), {"to": Stage.APPLIED}, **HTMX)
    assert response.status_code == 409
    assert "final stage" in response.content.decode()


def test_move_toast_offers_undo_and_undo_works(signed_in, user, make_application):
    app = make_application(user)
    response = signed_in.post(reverse("tracker:stage", args=[app.pk]), {"to": Stage.APPLIED}, **HTMX)
    assert reverse("tracker:undo", args=[app.pk]) in response["HX-Trigger"]

    response = signed_in.post(reverse("tracker:undo", args=[app.pk]), **HTMX)
    assert response.status_code == 204
    app.refresh_from_db()
    assert app.stage == Stage.SAVED


def test_undo_is_per_user(signed_in, other_user, make_application):
    theirs = make_application(other_user)
    ApplicationService(other_user).move(theirs, Stage.APPLIED)
    assert signed_in.post(reverse("tracker:undo", args=[theirs.pk])).status_code == 404


def test_edit_form_offers_only_allowed_stages(user, make_application):
    app = make_application(user, stage=Stage.INTERVIEW)
    choices = [value for value, _ in ApplicationForm(instance=app, user=user).fields["stage"].choices]
    assert choices == [Stage.INTERVIEW, Stage.OFFER, Stage.REJECTED]


def test_stage_change_through_the_edit_form_can_be_undone(signed_in, user, make_application):
    app = make_application(user, stage=Stage.APPLIED)
    data = {"company": app.company, "role": app.role, "stage": Stage.INTERVIEW}
    signed_in.post(reverse("tracker:edit", args=[app.pk]), data)
    app.refresh_from_db()
    assert app.stage == Stage.INTERVIEW
    assert ApplicationService(user).undo(app).stage == Stage.APPLIED


# --- Command line ---------------------------------------------------------------------------


def test_cli_and_website_share_the_same_logic_and_data(signed_in, user, make_application):
    app = make_application(user, company="Shopify")

    assert "moved to Applied" in cli(user, "move", str(app.pk), "applied")
    signed_in.post(reverse("tracker:stage", args=[app.pk]), {"to": Stage.INTERVIEW}, **HTMX)  # website
    assert f"#{app.pk}" in cli(user, "list", "--stage", "interview")

    # The same rule refuses the same move in both interfaces.
    with pytest.raises(CommandError, match="only move forward"):
        cli(user, "move", str(app.pk), "saved")
    assert signed_in.post(reverse("tracker:stage", args=[app.pk]), {"to": Stage.SAVED}, **HTMX).status_code == 409

    # A website move undone from the command line.
    assert "back in Applied" in cli(user, "undo", str(app.pk))
    history = cli(user, "history", str(app.pk))
    assert "via Command line" in history and "via Website" in history and "undo" in history


def test_cli_search_and_save(user, settings):
    settings.ADZUNA_APP_ID = ""
    output = cli(user, "search", "developer", "--rank", "pay")
    assert "sample postings" in output and "[s-5] Full-Stack Developer" in output
    assert "Saved #" in cli(user, "save", "s-5")
    assert Application.objects.for_user(user).get().history.get().via == Via.CLI


def test_cli_errors(user, other_user, make_application):
    theirs = make_application(other_user)
    with pytest.raises(CommandError, match="no application"):
        cli(user, "undo", str(theirs.pk))  # scoped to the --user account
    with pytest.raises(CommandError, match="No account"):
        call_command("cooptrack", "--user", "nobody@example.com", "list")
