"""Every user-owned model is reachable only through for_user()."""

import pytest
from django.contrib.auth.models import AnonymousUser

from tracker.models import Application, ResumeVersion, StageChange

pytestmark = pytest.mark.django_db


def test_applications_are_scoped_to_their_owner(user, other_user, make_application):
    mine = make_application(user)
    make_application(other_user)

    assert list(Application.objects.for_user(user)) == [mine]


def test_history_is_scoped_through_the_application(user, other_user, make_application):
    mine = make_application(user)
    make_application(other_user)

    assert {c.application_id for c in StageChange.objects.for_user(user)} == {mine.pk}


def test_resume_versions_are_scoped_to_their_owner(user, other_user):
    mine = ResumeVersion.objects.create(user=user, name="SWE v1")
    ResumeVersion.objects.create(user=other_user, name="SWE v1")

    assert list(ResumeVersion.objects.for_user(user)) == [mine]


def test_anonymous_users_see_nothing(user, make_application):
    make_application(user)

    assert not Application.objects.for_user(AnonymousUser()).exists()


def test_every_owned_model_declares_its_owner():
    for model in (Application, ResumeVersion, StageChange):
        assert model.owner_field, model
        assert hasattr(model.objects, "for_user"), model
