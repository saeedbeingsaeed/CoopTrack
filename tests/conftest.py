import pytest

from tracker.models import Application


@pytest.fixture(autouse=True)
def fast_test_settings(settings):
    # Tests don't run collectstatic, so skip the hashed-filename manifest.
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    # Real password hashing is deliberately slow; tests don't need that.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(email="ada@example.com", password="correct-horse-1")


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(email="mallory@example.com", password="correct-horse-2")


@pytest.fixture
def make_application():
    def make(user, **fields):
        fields.setdefault("company", "Shopify")
        fields.setdefault("role", "Backend Developer Intern")
        return Application.objects.create(user=user, **fields)

    return make
