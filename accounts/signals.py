from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver


@receiver(user_logged_out)
def delete_demo_user_on_logout(sender, request, user, **kwargs):
    # Demo accounts have no password, so once signed out they're useless.
    if user is not None and user.is_demo:
        user.delete()
