from allauth.account.models import EmailAddress
from allauth.socialaccount.signals import social_account_added
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver


@receiver(user_logged_out)
def delete_demo_user_on_logout(sender, request, user, **kwargs):
    # A demo account can't be signed back into (it has no password), so once the
    # visitor signs out its data is useless: delete it right away.
    if user is not None and user.is_demo:
        user.delete()


@receiver(social_account_added)
def verify_email_confirmed_by_google(sender, request, sociallogin, **kwargs):
    """
    When an existing email/password account signs in with Google for the first
    time, allauth links the two but leaves the email marked unverified. Google
    has just proved the person owns that address, so record it as verified.
    That's what lets them receive reminder emails.
    """
    user = sociallogin.user
    for address in sociallogin.email_addresses:
        if address.verified and address.email.lower() == user.email.lower():
            record, _ = EmailAddress.objects.get_or_create(
                user=user, email__iexact=address.email, defaults={"email": user.email, "primary": True}
            )
            record.set_verified()
