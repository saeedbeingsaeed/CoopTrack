import pytest
from django.urls import reverse

from accounts import demo
from accounts.models import DeletedAccount, User
from tracker.models import Application, ResumeVersion, StageChange

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


def test_delete_page_asks_first(signed_in, user):
    content = signed_in.get(reverse("delete_account")).content.decode()

    assert "Delete your account?" in content
    assert User.objects.filter(pk=user.pk).exists()


def test_deleting_needs_the_confirmation_word(signed_in, user):
    response = signed_in.post(reverse("delete_account"), {"confirm": "yes"})

    assert "Type delete to confirm." in response.content.decode()
    assert User.objects.filter(pk=user.pk).exists()


def test_deleting_removes_everything_and_signs_out(signed_in, user, make_application):
    application = make_application(user)
    application.move_to(1)
    ResumeVersion.objects.create(user=user, name="v1")

    response = signed_in.post(reverse("delete_account"), {"confirm": " Delete "}, follow=True)

    assert response.redirect_chain[-1][0] == reverse("landing")
    assert "have been deleted" in response.content.decode()
    assert not User.objects.filter(pk=user.pk).exists()
    assert not Application.objects.exists()
    assert not StageChange.objects.exists()
    assert not ResumeVersion.objects.exists()
    assert not response.context["user"].is_authenticated


def test_deletion_leaves_an_anonymous_record(signed_in, user, make_application):
    make_application(user)
    make_application(user)

    signed_in.post(reverse("delete_account"), {"confirm": "delete"})

    record = DeletedAccount.objects.get()
    assert record.application_count == 2
    assert record.signed_up_with == "password"
    assert record.joined_at == user.date_joined
    # Nothing identifying is kept.
    stored = " ".join(str(getattr(record, f.attname)) for f in DeletedAccount._meta.fields)
    assert user.email not in stored


def test_deleting_my_account_leaves_others_alone(signed_in, user, other_user, make_application):
    theirs = make_application(other_user)

    signed_in.post(reverse("delete_account"), {"confirm": "delete"})

    assert User.objects.filter(pk=other_user.pk).exists()
    assert Application.objects.filter(pk=theirs.pk).exists()


def test_demo_accounts_cannot_use_the_delete_page(client):
    client.post(reverse("demo"))
    response = client.post(reverse("delete_account"), {"confirm": "delete"})

    assert response.url == reverse("settings")
    assert not DeletedAccount.objects.exists()


def test_settings_links_to_deletion_and_privacy(signed_in):
    content = signed_in.get(reverse("settings")).content.decode()
    assert reverse("delete_account") in content
    assert reverse("privacy") in content


def test_every_page_links_to_privacy(client, signed_in):
    from django.test import Client

    for page in [reverse("tracker:board"), reverse("tracker:table"), reverse("settings")]:
        assert f'href="{reverse("privacy")}"' in signed_in.get(page).content.decode(), page
    anonymous = Client()
    for page in [reverse("landing"), reverse("account_login"), reverse("account_signup")]:
        assert f'href="{reverse("privacy")}"' in anonymous.get(page).content.decode(), page


def test_metrics_count_deletions(client, signed_in, django_user_model):
    signed_in.post(reverse("delete_account"), {"confirm": "delete"})
    admin = django_user_model.objects.create_user(email="admin@example.com", password="x", is_staff=True)
    client.force_login(admin)

    assert client.get(reverse("metrics")).context["metrics"]["deleted"] == 1


# --- Demo rate limit ------------------------------------------------------------------------


def test_demo_creation_is_limited_per_hour(client, settings, monkeypatch):
    monkeypatch.setattr(demo, "DEMOS_PER_HOUR", 2)
    for _ in range(2):
        demo.create_demo_user()

    response = client.post(reverse("demo"), follow=True)

    assert User.objects.filter(is_demo=True).count() == 2
    assert response.redirect_chain[-1][0] == reverse("landing")
    assert "try again in a few minutes" in response.content.decode()


def test_old_demos_do_not_count_toward_the_limit(client, monkeypatch):
    import datetime

    from django.utils import timezone

    monkeypatch.setattr(demo, "DEMOS_PER_HOUR", 1)
    old = demo.create_demo_user()
    User.objects.filter(pk=old.pk).update(date_joined=timezone.now() - datetime.timedelta(hours=2))

    client.post(reverse("demo"))

    assert User.objects.filter(is_demo=True).count() == 2


def test_account_menu_links_to_privacy_for_real_and_demo_users(signed_in):
    from django.test import Client

    demo_client = Client()
    demo_client.post(reverse("demo"))
    for client in (signed_in, demo_client):
        html = client.get(reverse("tracker:board")).content.decode()
        menu = html[html.index('aria-label="Account menu"') : html.index("</header>")]
        assert f'href="{reverse("privacy")}"' in menu
