"""
One user must never be able to view, edit, move or delete another user's data.
Each test signs in as `user` and goes after `other_user`'s rows.
"""

import pytest
from django.urls import reverse

from tracker.models import Application, ResumeVersion, Stage

pytestmark = pytest.mark.django_db


@pytest.fixture
def theirs(other_user, make_application):
    return make_application(other_user, company="Their Company", notes="private notes")


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


@pytest.mark.parametrize("name", ["detail", "edit", "delete"])
def test_cannot_view_another_users_application(signed_in, theirs, name):
    response = signed_in.get(reverse(f"tracker:{name}", args=[theirs.pk]))
    assert response.status_code == 404


def test_cannot_edit_another_users_application(signed_in, theirs):
    response = signed_in.post(reverse("tracker:edit", args=[theirs.pk]), {"company": "Hacked", "role": "x", "stage": 0})

    assert response.status_code == 404
    theirs.refresh_from_db()
    assert theirs.company == "Their Company"


def test_cannot_delete_another_users_application(signed_in, theirs):
    response = signed_in.post(reverse("tracker:delete", args=[theirs.pk]))

    assert response.status_code == 404
    assert Application.objects.filter(pk=theirs.pk).exists()


def test_cannot_move_another_users_application(signed_in, theirs):
    response = signed_in.post(reverse("tracker:stage", args=[theirs.pk]), {"to": Stage.OFFER})

    assert response.status_code == 404
    theirs.refresh_from_db()
    assert theirs.stage == Stage.SAVED
    assert theirs.history.count() == 1


def test_list_and_search_never_show_another_users_applications(signed_in, user, theirs, make_application):
    make_application(user, company="My Company")

    page = signed_in.get(reverse("tracker:table")).content.decode()
    search = signed_in.get(reverse("tracker:table"), {"q": "Their"}).content.decode()
    notes_search = signed_in.get(reverse("tracker:table"), {"q": "private"}).content.decode()

    assert "My Company" in page
    assert "Their Company" not in page + search + notes_search


def test_stage_counts_only_include_my_applications(signed_in, user, theirs, make_application):
    make_application(user)

    response = signed_in.get(reverse("tracker:table"))

    assert response.context["searched_total"] == 1


def test_cannot_attach_another_users_resume_version(signed_in, user, other_user):
    their_resume = ResumeVersion.objects.create(user=other_user, name="Their resume")

    response = signed_in.post(
        reverse("tracker:create"),
        {"company": "Acme", "role": "Intern", "stage": Stage.SAVED, "resume_version": their_resume.pk},
    )

    assert response.status_code == 200  # the form is shown again with an error
    assert "resume_version" in response.context["form"].errors
    assert not Application.objects.filter(user=user).exists()


def test_cannot_take_over_another_users_application_by_editing_mine(signed_in, user, theirs, make_application):
    """Posting a `user` field is ignored: the form doesn't include it and save() sets the owner."""
    mine = make_application(user)

    signed_in.post(
        reverse("tracker:edit", args=[mine.pk]), {"company": "Mine", "role": "x", "stage": 0, "user": theirs.user_id}
    )

    mine.refresh_from_db()
    assert mine.user == user


def test_resume_versions_are_private(signed_in, other_user):
    their_resume = ResumeVersion.objects.create(user=other_user, name="Their resume")

    page = signed_in.get(reverse("tracker:resumes")).content.decode()
    delete = signed_in.post(reverse("tracker:resume_delete", args=[their_resume.pk]))

    assert "Their resume" not in page
    assert delete.status_code == 404
    assert ResumeVersion.objects.filter(pk=their_resume.pk).exists()


def test_new_resume_name_matching_another_users_is_not_reused(signed_in, user, other_user):
    their_resume = ResumeVersion.objects.create(user=other_user, name="SWE v1")

    signed_in.post(
        reverse("tracker:create"), {"company": "Acme", "role": "Intern", "stage": Stage.SAVED, "new_resume": "SWE v1"}
    )

    application = Application.objects.get(user=user)
    assert application.resume_version != their_resume
    assert application.resume_version.user == user
