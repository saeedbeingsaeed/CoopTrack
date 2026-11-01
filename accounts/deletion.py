"""Self-service account deletion."""

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import logout
from django.db import transaction

from .models import DeletedAccount


@transaction.atomic
def delete_account(request, user):
    """
    Delete the user and everything they own (applications, history and resume
    versions go with them through on_delete=CASCADE), keeping only an
    anonymous note so the admin can count deletions.
    """
    has_google = SocialAccount.objects.filter(user=user).exists()
    signed_up_with = "both" if has_google and user.has_usable_password() else "google" if has_google else "password"
    DeletedAccount.objects.create(
        joined_at=user.date_joined,
        application_count=user.applications.count(),
        signed_up_with=signed_up_with,
    )
    logout(request)  # end the session first, so nothing keeps pointing at the deleted user
    user.delete()
