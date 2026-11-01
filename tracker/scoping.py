# Which rows a user can see, decided in one place. User-owned models use
# OwnedQuerySet and say who owns them in `owner_field`; views use OwnedObjectMixin.
# Someone else's object just isn't in the queryset, so it's a 404.

from django.db import models


class OwnedQuerySet(models.QuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(**{self.model.owner_field: user})


class OwnedObjectMixin:
    model = None

    def get_queryset(self):
        return self.model.objects.for_user(self.request.user)
