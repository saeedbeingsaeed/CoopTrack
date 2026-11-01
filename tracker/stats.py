# Numbers for the stats page, all worked out in SQL.
#
# Applied = ever reached Applied or later.
# Response = ever reached OA, Interview, Offer or Rejected (a rejection counts, silence doesn't).
# Furthest stage ignores Rejected, so "rejected after the interview" still counts as Interview.

import datetime

from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery
from django.db.models.functions import TruncWeek
from django.utils import timezone

from .models import Application, Stage, StageChange

WEEKS_SHOWN = 12
PIPELINE = [Stage.APPLIED, Stage.ONLINE_ASSESSMENT, Stage.INTERVIEW, Stage.OFFER]


def _annotated(user):
    history = StageChange.objects.filter(application=OuterRef("pk"))
    furthest = (
        history.filter(to_stage__lt=Stage.REJECTED)
        .values("application")
        .annotate(furthest=Max("to_stage"))
        .values("furthest")
    )
    return Application.objects.for_user(user).annotate(
        was_applied=Exists(history.filter(to_stage__gte=Stage.APPLIED)),
        got_response=Exists(history.filter(to_stage__gte=Stage.ONLINE_ASSESSMENT)),
        furthest=Subquery(furthest),
    )


def rate(part, whole):
    return round(100 * part / whole) if whole else None


def summary(user):
    reached = {f"reached_{stage.value}": Count("pk", filter=Q(furthest__gte=stage)) for stage in PIPELINE}
    # Includes jobs added straight to Rejected.
    reached[f"reached_{Stage.APPLIED.value}"] = Count("pk", filter=Q(was_applied=True))
    totals = _annotated(user).aggregate(
        total=Count("pk"),
        applied=Count("pk", filter=Q(was_applied=True)),
        responded=Count("pk", filter=Q(was_applied=True, got_response=True)),
        rejected=Count("pk", filter=Q(stage=Stage.REJECTED)),
        **reached,
    )
    applied = totals["applied"]
    funnel = []
    for stage in PIPELINE:
        count = totals[f"reached_{stage.value}"]
        funnel.append({"stage": stage, "count": count, "percent": rate(count, applied)})
    return {
        "total": totals["total"],
        "applied": applied,
        "responded": totals["responded"],
        "response_rate": rate(totals["responded"], applied),
        "interviews": totals[f"reached_{Stage.INTERVIEW.value}"],
        "offers": totals[f"reached_{Stage.OFFER.value}"],
        "rejected": totals["rejected"],
        "funnel": funnel,
    }


def per_week(user, today=None):
    today = today or timezone.localdate()
    this_monday = today - datetime.timedelta(days=today.weekday())
    first_monday = this_monday - datetime.timedelta(weeks=WEEKS_SHOWN - 1)
    counts = dict(
        Application.objects.for_user(user)
        .filter(date_applied__gte=first_monday, date_applied__lte=today)
        .annotate(week=TruncWeek("date_applied"))
        .values("week")
        .annotate(n=Count("pk"))
        .values_list("week", "n")
    )
    # Fill in weeks with no applications as 0.
    weeks = [first_monday + datetime.timedelta(weeks=i) for i in range(WEEKS_SHOWN)]
    counts = {_as_date(week): n for week, n in counts.items()}
    return [{"week": week, "count": counts.get(week, 0)} for week in weeks]


def _as_date(value):
    # TruncWeek can give a datetime on some databases.
    return value.date() if isinstance(value, datetime.datetime) else value


def per_resume(user):
    rows = (
        _annotated(user)
        .filter(was_applied=True)
        .values("resume_version__name")
        .annotate(applied=Count("pk"), responded=Count("pk", filter=Q(got_response=True)))
        .order_by("-applied", "resume_version__name")
    )
    return [
        {
            "name": row["resume_version__name"],
            "applied": row["applied"],
            "responded": row["responded"],
            "rate": rate(row["responded"], row["applied"]),
        }
        for row in rows
    ]
