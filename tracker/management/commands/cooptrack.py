# CoopTrack from the terminal (the second interface). Same database and same
# ApplicationService as the website; this file only parses arguments and prints.
#
#   python manage.py cooptrack --user you@example.com list --stage applied
#   python manage.py cooptrack --user you@example.com move 12 interview
#   python manage.py cooptrack --user you@example.com undo 12
#   python manage.py cooptrack --user you@example.com history 12
#   python manage.py cooptrack --user you@example.com search "developer co-op" --where Hamilton --rank student
#   python manage.py cooptrack --user you@example.com save adzuna-123456

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.domain.errors import CoopTrackError
from tracker.domain.ranking import DEFAULT_RANKING, RANKINGS
from tracker.models import Stage, Via
from tracker.services import ApplicationService

# "applied", "online-assessment" (or "oa"), ...
STAGE_NAMES = {stage.label.lower().replace(" ", "-"): stage for stage in Stage} | {"oa": Stage.ONLINE_ASSESSMENT}


def parse_stage(text):
    try:
        return STAGE_NAMES[text.lower()]
    except KeyError:
        raise CommandError(f"Unknown stage “{text}”. Use one of: {', '.join(STAGE_NAMES)}.") from None


class Command(BaseCommand):
    help = "CoopTrack from the command line: list, move, undo and search, on the same data as the website."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="email address of the account to act as")
        sub = parser.add_subparsers(dest="action", required=True)

        p = sub.add_parser("list", help="list applications")
        p.add_argument("--stage", type=parse_stage, help="only this stage")

        p = sub.add_parser("move", help="move an application to another stage")
        p.add_argument("id", type=int)
        p.add_argument("stage", type=parse_stage)

        p = sub.add_parser("undo", help="undo an application's last move")
        p.add_argument("id", type=int)

        p = sub.add_parser("history", help="show every stage change of an application")
        p.add_argument("id", type=int)

        p = sub.add_parser("search", help="search job postings (Adzuna)")
        p.add_argument("keywords")
        p.add_argument("--where", default="")
        p.add_argument("--rank", default=DEFAULT_RANKING, choices=list(RANKINGS))

        p = sub.add_parser("save", help="save a posting from a search to the board")
        p.add_argument("posting_id")

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(email__iexact=options["user"]).first()
        if user is None:
            raise CommandError(f"No account with the email {options['user']}.")
        service = ApplicationService(user, via=Via.CLI)
        try:
            getattr(self, f"do_{options['action']}")(service, options)
        except CoopTrackError as problem:
            raise CommandError(str(problem)) from problem

    def do_list(self, service, options):
        applications = service.applications(options["stage"]).order_by("stage", "company")
        if not applications:
            self.stdout.write("No applications.")
        for a in applications:
            self.stdout.write(f"#{a.pk:<5} {a.get_stage_display():<18} {a.company} · {a.role}")

    def do_move(self, service, options):
        application, moved = service.move(options["id"], options["stage"])
        if not moved:
            self.stdout.write(f"{application.company} is already in {application.get_stage_display()}.")
            return
        nxt = ", ".join(label for _, label in application.allowed_moves) or "none (final stage)"
        self.stdout.write(self.style.SUCCESS(f"{application.company} moved to {application.get_stage_display()}."))
        self.stdout.write(f"Next possible: {nxt}. Undo with: undo {application.pk}")

    def do_undo(self, service, options):
        application = service.undo(options["id"])
        self.stdout.write(
            self.style.SUCCESS(f"Undone: {application.company} is back in {application.get_stage_display()}.")
        )

    def do_history(self, service, options):
        for change in service.history(options["id"]):
            when = timezone.localtime(change.changed_at).strftime("%Y-%m-%d %H:%M")
            start = change.get_from_stage_display() or "(added)"
            action = "undo" if change.is_undo else "move" if change.from_stage is not None else "add"
            self.stdout.write(
                f"{when}  {action:<5} {start:>18} → {change.get_to_stage_display():<18} via {change.get_via_display()}"
            )

    def do_search(self, service, options):
        results = service.search_jobs(options["keywords"], options["where"], options["rank"])
        source = "sample postings (no Adzuna keys set)" if results.is_sample else "Adzuna"
        self.stdout.write(f"{len(results.postings)} results from {source}, sorted by {results.ranking.label.lower()}:")
        for p in results.postings:
            extra = " · ".join(x for x in (p.pay, p.location) if x)
            self.stdout.write(f"  [{p.id}] {p.title} · {p.company}" + (f" · {extra}" if extra else ""))
        if results.postings:
            self.stdout.write("Save one with: save <id>")

    def do_save(self, service, options):
        application, created = service.save_posting(options["posting_id"])
        verb = "Saved" if created else "Already on your board:"
        self.stdout.write(self.style.SUCCESS(f"{verb} #{application.pk} {application.company} · {application.role}"))
