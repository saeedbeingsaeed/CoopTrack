"""
Demo mode: "Try the demo" creates a throwaway user filled with sample data.

Every visitor gets their own demo user, so nothing they do is seen by anyone
else, and the normal per-user scoping keeps demo data and real data apart
exactly as it keeps two real users apart. Demo users are deleted when they sign
out, and any left over are deleted by the daily job after DEMO_LIFETIME.
"""

import datetime
import secrets

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from tracker.models import Application, ResumeVersion, Stage, StageChange

DEMO_LIFETIME = datetime.timedelta(hours=24)
# At most this many new demos per hour across the whole site. Each demo is ~60
# rows, so even a script hammering the button can add at most a few MB a day
# (and demos are purged after 24 hours), far below Supabase's free 500 MB.
DEMOS_PER_HOUR = 30
SV, AP, OA, IV, OF, RJ = (
    Stage.SAVED,
    Stage.APPLIED,
    Stage.ONLINE_ASSESSMENT,
    Stage.INTERVIEW,
    Stage.OFFER,
    Stage.REJECTED,
)

# (company, role, location, pay, resume, deadline in days from today or None,
#  history as (stage, days ago) oldest first, notes)
SAMPLE = [
    ("Shopify", "Backend Developer Intern", "Toronto, ON · Remote", "$32/hr", "SWE v3", 3,
     [(SV, 40), (AP, 38), (OA, 30), (IV, 9)], "Referred by Priya (4A CS). Round 2 is pair programming."),
    ("RBC", "Data Analyst Co-op", "Toronto, ON", "$27/hr", "Data v1", None,
     [(AP, 33), (IV, 20), (OF, 4)], "Offer expires in two weeks. Ask about return offers."),
    ("Wealthsimple", "Software Engineer Intern", "Toronto, ON · Hybrid", "$35/hr", "SWE v3", 2,
     [(AP, 21), (OA, 6)], "HackerRank OA: 2 questions, 90 minutes."),
    ("Google", "Software Engineering Intern, Summer", "Waterloo, ON", "", "SWE v2", None,
     [(AP, 52), (OA, 44), (RJ, 31)], ""),
    ("Kinaxis", "Software Developer Co-op", "Ottawa, ON", "$28/hr", None, 1,
     [(SV, 3)], "Posting closes tomorrow. Ask Sam about the team."),
    ("Ubisoft", "Gameplay Programmer Co-op", "Montréal, QC", "", "SWE v2", None,
     [(AP, 45), (RJ, 27)], ""),
    ("Clio", "Platform Engineering Co-op", "Burnaby, BC · Hybrid", "$30/hr", "SWE v3", None,
     [(AP, 25)], "Applied through the co-op portal."),
    ("Microsoft", "Explore Intern", "Vancouver, BC", "$8,500/month", "SWE v2", None,
     [(AP, 60), (OA, 50), (IV, 38), (RJ, 30)], "Made it to the final round."),
    ("Interac", "QA Automation Co-op", "Toronto, ON", "$25/hr", "SWE v2", None,
     [(AP, 19)], ""),
    ("Cohere", "ML Engineering Intern", "Toronto, ON", "", "SWE v3", 6,
     [(SV, 8)], "Need a project writeup before applying."),
    ("Faire", "Software Engineer Intern", "Waterloo, ON · Hybrid", "$34/hr", "SWE v3", None,
     [(AP, 16), (OA, 11), (IV, 2)], "Onsite next Tuesday: system design + behavioural."),
    ("Bell", "Data Science Co-op", "Mississauga, ON", "$24/hr", "Data v1", None,
     [(AP, 28), (RJ, 15)], ""),
    ("Ecobee", "Firmware Developer Co-op", "Toronto, ON", "$26/hr", "SWE v2", None,
     [(AP, 12)], ""),
    ("Questrade", "Full-Stack Developer Co-op", "Toronto, ON", "", "SWE v3", None,
     [(AP, 9), (OA, 4)], ""),
    ("Ada", "Product Engineer Intern", "Toronto, ON · Remote", "", "SWE v3", None,
     [(AP, 6)], ""),
    ("Thomson Reuters", "Data Analyst Co-op", "Toronto, ON", "$25/hr", "Data v1", None,
     [(AP, 35), (OA, 24)], ""),
    ("1Password", "Developer Intern", "Remote (Canada)", "$33/hr", None, 12,
     [(SV, 5)], ""),
    ("Nokia", "Software Test Co-op", "Ottawa, ON", "", "SWE v2", None,
     [(AP, 48)], ""),
]  # fmt: skip


@transaction.atomic
def create_demo_user():
    """A fresh demo user with sample data, in a handful of queries whatever the sample size."""
    now = timezone.now()
    today = timezone.localdate()
    user = get_user_model().objects.create_user(
        # .invalid is a reserved top-level domain: these addresses can never receive email.
        email=f"demo-{secrets.token_hex(6)}@demo.invalid",
        password=None,  # unusable password: the only way in is the demo button
        first_name="Demo",
        is_demo=True,
        reminders_enabled=False,
    )
    resumes = {name: ResumeVersion.objects.create(user=user, name=name) for name in ("SWE v2", "SWE v3", "Data v1")}

    applications, histories = [], []
    for company, role, location, pay, resume, deadline, history, notes in SAMPLE:
        applied = next((days for stage, days in history if stage != SV), None)
        applications.append(
            Application(
                user=user,
                company=company,
                role=role,
                location=location,
                pay=pay,
                notes=notes,
                posting_url=f"https://careers.example.com/{company.lower().replace(' ', '-')}",
                resume_version=resumes.get(resume),
                stage=history[-1][0],
                date_applied=today - datetime.timedelta(days=applied) if applied is not None else None,
                deadline=today + datetime.timedelta(days=deadline) if deadline is not None else None,
            )
        )
        histories.append(history)

    # bulk_create skips Application.save(), so the history rows are written here
    # explicitly, with the backdated times the sample describes.
    Application.objects.bulk_create(applications)
    changes = []
    for application, history in zip(applications, histories, strict=True):
        previous = None
        for stage, days_ago in history:
            changes.append(
                StageChange(
                    application=application,
                    from_stage=previous,
                    to_stage=stage,
                    changed_at=now - datetime.timedelta(days=days_ago, hours=3),
                )
            )
            previous = stage
    StageChange.objects.bulk_create(changes)
    # Date each application's last update to its latest change, so "no update in
    # 2 weeks" looks real. bulk_update writes these values as given (auto_now doesn't apply).
    for application, history in zip(applications, histories, strict=True):
        application.updated_at = now - datetime.timedelta(days=history[-1][1], hours=3)
    Application.objects.bulk_update(applications, ["updated_at"])
    return user


def too_many_recent_demos(now=None):
    """
    A site-wide limit, counted from the database. Unlike a per-IP limit, it
    can't be dodged by faking addresses, and it works across all server
    processes without a shared cache.
    """
    since = (now or timezone.now()) - datetime.timedelta(hours=1)
    return get_user_model().objects.filter(is_demo=True, date_joined__gte=since).count() >= DEMOS_PER_HOUR


def purge_expired(now=None):
    """Delete demo users older than DEMO_LIFETIME. Returns how many were deleted."""
    cutoff = (now or timezone.now()) - DEMO_LIFETIME
    deleted, per_model = get_user_model().objects.filter(is_demo=True, date_joined__lt=cutoff).delete()
    return per_model.get(get_user_model()._meta.label, 0)
