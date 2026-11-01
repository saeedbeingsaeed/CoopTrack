from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import logout
from django.db import transaction

from .models import DeletedAccount


@transaction.atomic
def delete_account(request, user):
    # Everything they own goes with them (CASCADE); only an anonymous count is kept.
    has_google = SocialAccount.objects.filter(user=user).exists()
    signed_up_with = "both" if has_google and user.has_usable_password() else "google" if has_google else "password"
    DeletedAccount.objects.create(
        joined_at=user.date_joined,
        application_count=user.applications.count(),
        signed_up_with=signed_up_with,
    )
    logout(request)
    user.delete()
