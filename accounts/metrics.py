"""Usage numbers for the admin-only metrics page, counted by the database."""

import datetime

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import TruncWeek
from django.utils import timezone

from tracker.models import Application, StageChange

from .models import DeletedAccount

WEEKS = 8


def collect(now=None):
    now = now or timezone.now()
    week_ago, month_ago = now - datetime.timedelta(days=7), now - datetime.timedelta(days=30)
    users = get_user_model().objects

    def active_since(moment):
        # Active = changed something: edited or added an application, or moved one.
        # This comes from data we already store, so nothing extra is tracked.
        return Exists(Application.objects.filter(user=OuterRef("pk"), updated_at__gte=moment)) | Exists(
            StageChange.objects.filter(application__user=OuterRef("pk"), changed_at__gte=moment)
        )

    real = users.filter(is_demo=False)
    totals = real.aggregate(
        signups=Count("pk"),
        signups_7d=Count("pk", filter=Q(date_joined__gte=week_ago)),
        signups_30d=Count("pk", filter=Q(date_joined__gte=month_ago)),
        active_7d=Count("pk", filter=active_since(week_ago)),
        active_30d=Count("pk", filter=active_since(month_ago)),
    )
    totals["demos_7d"] = users.filter(is_demo=True, date_joined__gte=week_ago).count()
    totals["applications"] = Application.objects.filter(user__is_demo=False).count()
    totals.update(
        DeletedAccount.objects.aggregate(
            deleted=Count("pk"), deleted_30d=Count("pk", filter=Q(deleted_at__gte=month_ago))
        )
    )

    first_week = (now - datetime.timedelta(weeks=WEEKS - 1)).date()
    first_week -= datetime.timedelta(days=first_week.weekday())
    per_week = dict(
        real.filter(date_joined__date__gte=first_week)
        .annotate(week=TruncWeek("date_joined"))
        .values("week")
        .annotate(n=Count("pk"))
        .values_list("week", "n")
    )
    per_week = {(w.date() if isinstance(w, datetime.datetime) else w): n for w, n in per_week.items()}
    weeks = [first_week + datetime.timedelta(weeks=i) for i in range(WEEKS)]
    totals["weekly"] = [{"week": w, "count": per_week.get(w, 0)} for w in weeks]
    totals["weekly_max"] = max([row["count"] for row in totals["weekly"]] + [1])
    return totals
