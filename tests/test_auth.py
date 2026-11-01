import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_landing_page_is_public(client):
    response = client.get(reverse("landing"))
    assert response.status_code == 200
    assert b"Every application" in response.content


def test_landing_page_sends_signed_in_users_to_the_app(client, user):
    client.force_login(user)
    assert client.get(reverse("landing")).url == reverse("tracker:board")


def test_signup_creates_an_account_and_signs_in(client):
    response = client.post(
        reverse("account_signup"), {"email": "new@example.com", "password1": "a-long-passphrase-9"}, follow=True
    )

    assert response.redirect_chain[-1][0] == reverse("tracker:board")
    assert response.context["user"].email == "new@example.com"


def test_signup_rejects_a_duplicate_email(client, user):
    response = client.post(reverse("account_signup"), {"email": user.email, "password1": "a-long-passphrase-9"})

    assert response.status_code == 200
    assert User.objects.filter(email=user.email).count() == 1


def test_login_with_email_and_password(client, user):
    response = client.post(reverse("account_login"), {"login": user.email, "password": "correct-horse-1"})
    assert response.url == reverse("tracker:board")


def test_google_button_hidden_until_configured(client, settings):
    settings.GOOGLE_CLIENT_ID = ""
    assert b"Continue with Google" not in client.get(reverse("account_login")).content


def test_health_check_skips_auth_and_database(client, django_assert_num_queries):
    with django_assert_num_queries(0):
        assert client.get(reverse("healthz")).content == b"ok"


def _app_urls(resolver=None, prefix=""):
    """Yield every named URL in the tracker app."""
    for entry in (resolver or get_resolver()).url_patterns:
        if isinstance(entry, URLResolver):
            yield from _app_urls(entry, prefix + (f"{entry.namespace}:" if entry.namespace else ""))
        elif isinstance(entry, URLPattern) and entry.name and prefix == "tracker:":
            yield prefix + entry.name


def test_every_app_page_requires_sign_in(client):
    """Guards future pages too: any new tracker URL without kwargs is checked automatically."""
    names = list(_app_urls())
    assert names
    for name in names:
        try:
            url = reverse(name)
        except Exception:
            url = reverse(name, kwargs={"pk": 1})
        response = client.get(url)
        assert response.status_code == 302, name
        assert response.url.startswith(reverse("account_login")), name


def test_user_manager_creates_users_by_email():
    admin = User.objects.create_superuser(email="ADMIN@Example.com", password="x")
    assert admin.email == "ADMIN@example.com"  # domain is normalised
    assert admin.is_staff and admin.is_superuser
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="x")


def test_custom_404_page(client, settings):
    settings.DEBUG = False
    response = client.get("/no-such-page/")
    assert response.status_code == 404
    assert b"Page not found" in response.content


def test_privacy_page_is_public_and_shows_the_contact(client, settings):
    settings.CONTACT_EMAIL = "help@example.com"

    response = client.get(reverse("privacy"))

    assert response.status_code == 200
    assert "help@example.com" in response.content.decode()
    assert reverse("privacy") in client.get(reverse("landing")).content.decode()
