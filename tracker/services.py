# The core logic, shared by both interfaces: the website (views.py) and the CLI
# (management/commands/cooptrack.py). Neither of those has any rules of its own;
# they turn their input into a call here and show the result or error their own
# way. `via` is saved on every history row so you can tell which one made a change.

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from .domain.errors import NotFound, NothingToUndo
from .domain.postings import Posting, SampleJobSource
from .domain.ranking import DEFAULT_RANKING, RankingStrategy, get_ranking
from .domain.stages import Stage
from .models import Application, JobPosting, Via


def get_job_source():
    if settings.ADZUNA_APP_ID and settings.ADZUNA_APP_KEY:
        from .adzuna import AdzunaJobSource

        return AdzunaJobSource(settings.ADZUNA_APP_ID, settings.ADZUNA_APP_KEY, settings.ADZUNA_COUNTRY)
    return SampleJobSource()


@dataclass(frozen=True)
class SearchResults:
    postings: list[Posting]
    ranking: RankingStrategy
    is_sample: bool


class ApplicationService:
    SEARCH_LIMIT = 20

    def __init__(self, user, via=Via.WEB, job_source=None):
        self.user = user
        self.via = via
        self.job_source = job_source

    def applications(self, stage=None):
        apps = Application.objects.for_user(self.user)
        return apps if stage is None else apps.filter(stage=stage)

    def get(self, application):
        # Accepts an id or an instance; either way it's re-checked against this user.
        pk = getattr(application, "pk", application)
        found = self.applications().filter(pk=pk).first()
        if found is None:
            raise NotFound(f"You have no application with id {pk}.")
        return found

    def history(self, application):
        return list(self.get(application).history.all())

    def move(self, application, stage):
        """Returns (application, moved). Raises InvalidMove if the stage rules say no."""
        application = self.get(application)
        stage = Stage(stage)
        if application.stage == stage:
            return application, False
        memento = application.create_memento()
        with transaction.atomic():
            application.move_to(stage, via=self.via)  # checks the rules before writing anything
            application.undo_history.push(memento)
        return application, True

    def undo(self, application):
        application = self.get(application)
        with transaction.atomic():
            memento = application.undo_history.pop()
            if memento is None:
                raise NothingToUndo(f"{application.company} has no move to undo.")
            application.restore(memento, via=self.via)
        return application

    def search_jobs(self, keywords, location="", ranking=DEFAULT_RANKING):
        strategy = get_ranking(ranking)
        source = self.job_source or get_job_source()
        postings = source.search(keywords.strip(), location.strip(), self.SEARCH_LIMIT)
        self._remember(postings)
        return SearchResults(strategy.rank(postings, keywords), strategy, source.is_sample)

    def save_posting(self, posting_id):
        """Adds a searched posting to the board in Saved. Returns (application, created)."""
        posting = JobPosting.objects.filter(pk=posting_id).first()
        if posting is None:
            raise NotFound(f"No posting with id {posting_id}. Run the search again first.")
        existing = self.applications().filter(posting_url=posting.url).first()
        if existing:
            return existing, False
        application = Application(
            user=self.user,
            company=posting.company[:120],
            role=posting.title[:120],
            location=posting.location[:120],
            pay=Posting(posting.pk, "", "", "", posting.salary_min, posting.salary_max, None, "").pay,
            posting_url=posting.url[:500],
            notes=posting.description,
            stage=Stage.SAVED,
        )
        application._change_via = self.via
        application.save()
        return application, True

    def saved_posting_urls(self, postings):
        urls = [p.url for p in postings]
        return set(self.applications().filter(posting_url__in=urls).values_list("posting_url", flat=True))

    def _remember(self, postings):
        # Keep search results in the database so `save` can find them later,
        # even from the CLI, which runs as a separate process.
        for p in postings:
            JobPosting.objects.update_or_create(
                pk=p.id,
                defaults={
                    "title": p.title[:300],
                    "company": p.company[:200],
                    "location": p.location[:200],
                    "salary_min": p.salary_min,
                    "salary_max": p.salary_max,
                    "created": p.created,
                    "url": p.url[:1000],
                    "description": p.description,
                },
            )
