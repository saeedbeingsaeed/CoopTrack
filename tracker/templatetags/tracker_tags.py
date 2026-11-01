from django import template
from django.utils import timezone
from django.utils.timesince import timesince

from tracker.models import Stage

register = template.Library()


@register.inclusion_tag("tracker/partials/deadline.html")
def deadline_badge(application):
    """
    A deadline with urgency: overdue and due-soon dates stand out. Closed
    applications (Offer or Rejected) show the date plainly, since it no longer matters.
    """
    deadline = application.deadline
    closed = application.stage in (Stage.OFFER, Stage.REJECTED)
    if deadline is None:
        return {"deadline": None}
    days = (deadline - timezone.localdate()).days
    if closed:
        tone, note = "plain", ""
    elif days < 0:
        tone, note = "overdue", "Overdue"
    elif days == 0:
        tone, note = "urgent", "Today"
    elif days == 1:
        tone, note = "urgent", "Tomorrow"
    elif days <= 3:
        tone, note = "soon", f"In {days} days"
    else:
        tone, note = "plain", ""
    return {"deadline": deadline, "tone": tone, "note": note}


@register.filter
def ago(moment):
    """ "just now", "5 minutes ago", "3 days ago": one unit, which is all a table needs."""
    if (timezone.now() - moment).total_seconds() < 60:
        return "just now"
    return f"{timesince(moment, depth=1)} ago"


@register.filter
def days_ago(moment):
    """Compact age for board cards: "today", "1d", "12d"."""
    days = (timezone.localdate() - timezone.localtime(moment).date()).days
    return "today" if days <= 0 else f"{days}d"
