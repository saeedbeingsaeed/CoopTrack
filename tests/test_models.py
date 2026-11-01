import datetime

import pytest

from tracker.models import Application, Stage, StageChange

pytestmark = pytest.mark.django_db


def test_creating_an_application_records_its_first_stage(user, make_application):
    app = make_application(user, stage=Stage.APPLIED)

    [change] = app.history.all()
    assert change.from_stage is None
    assert change.to_stage == Stage.APPLIED


def test_move_to_records_the_change(user, make_application):
    app = make_application(user)

    assert app.move_to(Stage.INTERVIEW) is True

    app.refresh_from_db()
    assert app.stage == Stage.INTERVIEW
    assert [(c.from_stage, c.to_stage) for c in app.history.all()] == [
        (None, Stage.SAVED),
        (Stage.SAVED, Stage.INTERVIEW),
    ]


def test_moving_to_the_same_stage_records_nothing(user, make_application):
    app = make_application(user, stage=Stage.APPLIED)

    assert app.move_to(Stage.APPLIED) is False
    assert app.history.count() == 1


def test_editing_other_fields_records_nothing(user, make_application):
    app = make_application(user)
    app.notes = "Referred by a friend"
    app.save()

    assert app.history.count() == 1


def test_changing_stage_through_a_loaded_object_is_recorded(user, make_application):
    """The edit form loads the object fresh and saves it; that path must record history too."""
    created = make_application(user)
    loaded = Application.objects.get(pk=created.pk)
    loaded.stage = Stage.OFFER
    loaded.save()

    assert StageChange.objects.filter(application=created, from_stage=Stage.SAVED, to_stage=Stage.OFFER).exists()


def test_deleting_an_application_deletes_its_history(user, make_application):
    app = make_application(user)
    app.move_to(Stage.APPLIED)
    app.delete()

    assert StageChange.objects.count() == 0


def test_stages_are_in_pipeline_order():
    assert list(Stage) == [
        Stage.SAVED,
        Stage.APPLIED,
        Stage.ONLINE_ASSESSMENT,
        Stage.INTERVIEW,
        Stage.OFFER,
        Stage.REJECTED,
    ]


def test_moving_past_saved_fills_in_the_applied_date(user, make_application):
    app = make_application(user)
    assert app.date_applied is None

    app.move_to(Stage.APPLIED)

    app.refresh_from_db()
    assert app.date_applied is not None


def test_an_existing_applied_date_is_kept(user, make_application):
    app = make_application(user, stage=Stage.APPLIED, date_applied=datetime.date(2026, 9, 1))
    app.move_to(Stage.INTERVIEW)

    app.refresh_from_db()
    assert app.date_applied == datetime.date(2026, 9, 1)
