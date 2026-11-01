"""
The one place that decides which rows a user may see.

Every model that belongs to a user gets OwnedQuerySet as its manager and names
the path to its owner in `owner_field`. Every view that touches those models
inherits OwnedObjectMixin, whose get_queryset() is built from for_user(). A view
never filters by user itself, so there is nothing to forget: asking for another
user's object simply isn't in the queryset, and Django answers 404.
"""

from django.db import models


class OwnedQuerySet(models.QuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(**{self.model.owner_field: user})


class OwnedObjectMixin:
    """For class-based views: limit get_queryset() (and so get_object()) to the user's rows."""

    model = None

    def get_queryset(self):
        return self.model.objects.for_user(self.request.user)
