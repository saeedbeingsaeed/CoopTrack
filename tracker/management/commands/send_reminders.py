import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker import reminders


class Command(BaseCommand):
    help = "Email each user their upcoming deadlines and applications with no update in 2 weeks."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List who would be emailed; send nothing.")
        parser.add_argument("--date", type=datetime.date.fromisoformat, help="Pretend today is YYYY-MM-DD (testing).")

    def handle(self, *args, dry_run=False, date=None, **options):
        today = date or timezone.localdate()
        sent, failed = reminders.send_all(today, dry_run=dry_run, stdout=self.stdout)
        verb = "Would send" if dry_run else "Sent"
        self.stdout.write(self.style.SUCCESS(f"{verb} {sent} reminder email{'s' if sent != 1 else ''} for {today}."))
        if failed:
            # A non-zero exit makes the GitHub Actions run show as failed, so you notice.
            raise CommandError(f"{failed} email{'s' if failed != 1 else ''} failed to send. See the log above.")
