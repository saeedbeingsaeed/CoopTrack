from django.core.management.base import BaseCommand

from accounts import demo


class Command(BaseCommand):
    help = "Delete demo accounts (and their sample data) older than 24 hours."

    def handle(self, *args, **options):
        deleted = demo.purge_expired()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired demo account{'s' if deleted != 1 else ''}."))
