from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from .scoping import OwnedQuerySet


class Stage(models.IntegerChoices):
    """
    Stored as small integers in pipeline order, so "how far did this get" is a
    plain Max() in SQL. Rejected is last but isn't progress; stats treat it
    separately.
    """

    SAVED = 0, "Saved"
    APPLIED = 1, "Applied"
    ONLINE_ASSESSMENT = 2, "Online Assessment"
    INTERVIEW = 3, "Interview"
    OFFER = 4, "Offer"
    REJECTED = 5, "Rejected"


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
        # Anything past Saved has been applied to; default the date to today so
        # it still counts in the per-week stats.
        if self.stage != Stage.SAVED and self.date_applied is None:
            self.date_applied = timezone.localdate()
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "date_applied"}
        with transaction.atomic():
            super().save(*args, **kwargs)
            if is_new or self.stage != previous:
                StageChange.objects.create(
                    application=self,
                    from_stage=None if is_new else previous,
                    to_stage=self.stage,
                )
        self._saved_stage = self.stage

    @classmethod
    def from_db(cls, *args, **kwargs):
        instance = super().from_db(*args, **kwargs)
        # Remember the stage as loaded so save() can tell whether it changed.
        instance._saved_stage = instance.__dict__.get("stage")
        return instance

    def move_to(self, stage):
        """Change the stage, recording history. Returns False if it was already there."""
        if self.stage == stage:
            return False
        self.stage = stage
        self.save(update_fields=["stage", "updated_at"])
        return True


class StageChange(models.Model):
    owner_field = "application__user"

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="history")
    from_stage = models.PositiveSmallIntegerField(choices=Stage, null=True, blank=True)  # null: just created
    to_stage = models.PositiveSmallIntegerField(choices=Stage)
    changed_at = models.DateTimeField(default=timezone.now)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ["changed_at", "id"]
        indexes = [models.Index(fields=["application", "changed_at"])]

    def __str__(self):
        start = self.get_from_stage_display() or "Created"
        return f"{start} → {self.get_to_stage_display()}"
