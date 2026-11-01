from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from .domain.stages import Stage, state_for
from .domain.undo import StageMemento, UndoHistory
from .scoping import OwnedQuerySet


class Via(models.TextChoices):
    # Which interface made a change; saved on every history row.
    WEB = "web", "Website"
    CLI = "cli", "Command line"
    IMPORT = "import", "CSV import"


class ResumeVersion(models.Model):
    owner_field = "user"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="resume_versions")
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="unique_resume_name_per_user")]

    def __str__(self):
        return self.name


class Application(models.Model):
    owner_field = "user"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="applications")
    company = models.CharField(max_length=120)
    role = models.CharField(max_length=120)
    posting_url = models.URLField("link to posting", max_length=500, blank=True)
    location = models.CharField(max_length=120, blank=True)
    pay = models.CharField(max_length=60, blank=True, help_text='Free text, e.g. "$28/hr" or "$5,000/month".')
    date_applied = models.DateField(null=True, blank=True)
    deadline = models.DateField(null=True, blank=True)
    stage = models.PositiveSmallIntegerField(choices=Stage, default=Stage.SAVED)
    notes = models.TextField(blank=True)
    resume_version = models.ForeignKey(
        ResumeVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="applications"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "stage"]),
            models.Index(fields=["user", "deadline"]),
            models.Index(fields=["user", "updated_at"]),
        ]

    def __str__(self):
        return f"{self.role} at {self.company}"

    def save(self, *args, **kwargs):
        """
        Saving is the single place stage history is written. Whatever changes
        the stage (the edit form, drag and drop, the keyboard menu, CSV import)
        goes through here, so no path can skip the history row. The application
        and its history row are saved in one transaction: both or neither.
        """
        is_new = self._state.adding
        previous = getattr(self, "_saved_stage", None)
        self.state.before_save(self)  # e.g. past Saved, fill in the applied date
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "date_applied"}
        with transaction.atomic():
            super().save(*args, **kwargs)
            if is_new or self.stage != previous:
                StageChange.objects.create(
                    application=self,
                    from_stage=None if is_new else previous,
                    to_stage=self.stage,
                    via=getattr(self, "_change_via", Via.WEB),
                    is_undo=getattr(self, "_change_is_undo", False),
                )
        self._saved_stage = self.stage
        self._change_is_undo = False

    @classmethod
    def from_db(cls, *args, **kwargs):
        instance = super().from_db(*args, **kwargs)
        # Remember the stage as loaded so save() can tell whether it changed.
        instance._saved_stage = instance.__dict__.get("stage")
        return instance

    # State pattern: Application is the context, the stage rules live in its state object.

    @property
    def state(self):
        return state_for(self.stage)

    @property
    def allowed_moves(self):
        return [(stage.value, stage.label) for stage in self.state.next_stages]

    def move_to(self, stage, via=Via.WEB):
        # Use ApplicationService.move() instead; it also saves a memento for Undo.
        if self.stage == stage:
            return False
        self.state.move(self, Stage(stage))
        self._change_via = via
        self.save(update_fields=["stage", "updated_at"])
        return True

    # Memento pattern: Application is the originator.

    def create_memento(self):
        return StageMemento(self.stage, self.date_applied)

    def restore(self, memento, via=Via.WEB):
        # Going back to an earlier state isn't a move, so the stage rules don't apply.
        self.stage = memento._stage
        self.date_applied = memento._date_applied
        self._change_via = via
        self._change_is_undo = True
        self.save(update_fields=["stage", "date_applied", "updated_at"])

    @property
    def undo_history(self):
        return UndoHistory(self)


class StageChange(models.Model):
    owner_field = "application__user"

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="history")
    from_stage = models.PositiveSmallIntegerField(choices=Stage, null=True, blank=True)  # null: just created
    to_stage = models.PositiveSmallIntegerField(choices=Stage)
    changed_at = models.DateTimeField(default=timezone.now)
    via = models.CharField(max_length=10, choices=Via, default=Via.WEB)
    is_undo = models.BooleanField(default=False)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ["changed_at", "id"]
        indexes = [models.Index(fields=["application", "changed_at"])]

    def __str__(self):
        start = self.get_from_stage_display() or "Created"
        return f"{start} → {self.get_to_stage_display()}"


class StageSnapshot(models.Model):
    # Where UndoHistory (the Memento caretaker) keeps its mementos.
    owner_field = "application__user"

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="snapshots")
    data = models.TextField()  # serialized StageMemento
    created_at = models.DateTimeField(default=timezone.now)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        indexes = [models.Index(fields=["application", "-created_at"])]

    def __str__(self):
        return f"Undo snapshot for {self.application}"


class JobPosting(models.Model):
    # Postings from recent searches, so "save" can find one by id. Public data, no owner.
    id = models.CharField(primary_key=True, max_length=60)
    title = models.CharField(max_length=300)
    company = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    salary_min = models.FloatField(null=True, blank=True)
    salary_max = models.FloatField(null=True, blank=True)
    created = models.DateTimeField(null=True, blank=True)
    url = models.URLField(max_length=1000)
    description = models.TextField(blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} at {self.company}"
