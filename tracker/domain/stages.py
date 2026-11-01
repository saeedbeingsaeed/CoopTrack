# State pattern.
#
# Application is the context: anything that depends on its stage is handed to a
# StageState object (application.state). Each state knows where an application
# can go next and what to do when it's saved in that stage.
#
# Rules: applications only move forward (skipping is fine), any open stage can
# go to Rejected, and Offer/Rejected are final. Mistakes are fixed with Undo
# (see undo.py), not by dragging a card backwards.
#
#   Saved -> Applied -> Online Assessment -> Interview -> Offer
#     \________\_______________\_______________\_______-> Rejected
#
# The stage is still stored as a small int so SQL can compare and aggregate it.

from __future__ import annotations

from django.db import models
from django.utils import timezone

from .errors import InvalidMove


class Stage(models.IntegerChoices):
    # Stored in pipeline order, so "how far did it get" is just Max() in SQL.
    # Rejected is last but isn't progress; stats treat it separately.
    SAVED = 0, "Saved"
    APPLIED = 1, "Applied"
    ONLINE_ASSESSMENT = 2, "Online Assessment"
    INTERVIEW = 3, "Interview"
    OFFER = 4, "Offer"
    REJECTED = 5, "Rejected"


class StageState:
    stage: Stage
    next_stages: tuple[Stage, ...] = ()

    @property
    def is_final(self):
        return not self.next_stages

    def can_move_to(self, target):
        return target in self.next_stages

    def move(self, application, target):
        if not self.can_move_to(target):
            raise InvalidMove(self.refusal(application, target))
        application.stage = target

    def before_save(self, application):
        pass

    def refusal(self, application, target):
        if target == self.stage:
            return f"{application.company} is already in {self.stage.label}."
        return (
            f"{application.company} can't go back from {self.stage.label} to {Stage(target).label}. "
            "Applications only move forward; use Undo to reverse a move."
        )


class AppliedOrLater(StageState):
    # Anything past Saved counts as applied, so fill in the date for the weekly stats.
    def before_save(self, application):
        if application.date_applied is None:
            application.date_applied = timezone.localdate()


class FinalState(AppliedOrLater):
    def refusal(self, application, target):
        if target == self.stage:
            return super().refusal(application, target)
        return (
            f"{self.stage.label} is a final stage, so {application.company} can't move to {Stage(target).label}. "
            "If the last move was a mistake, use Undo."
        )


class SavedState(StageState):
    stage = Stage.SAVED
    next_stages = (Stage.APPLIED, Stage.ONLINE_ASSESSMENT, Stage.INTERVIEW, Stage.OFFER, Stage.REJECTED)


class AppliedState(AppliedOrLater):
    stage = Stage.APPLIED
    next_stages = (Stage.ONLINE_ASSESSMENT, Stage.INTERVIEW, Stage.OFFER, Stage.REJECTED)


class OnlineAssessmentState(AppliedOrLater):
    stage = Stage.ONLINE_ASSESSMENT
    next_stages = (Stage.INTERVIEW, Stage.OFFER, Stage.REJECTED)


class InterviewState(AppliedOrLater):
    stage = Stage.INTERVIEW
    next_stages = (Stage.OFFER, Stage.REJECTED)


class OfferState(FinalState):
    stage = Stage.OFFER


class RejectedState(FinalState):
    stage = Stage.REJECTED


# States don't hold any data, so one shared instance of each is enough.
STATES = {
    s.stage: s
    for s in (SavedState(), AppliedState(), OnlineAssessmentState(), InterviewState(), OfferState(), RejectedState())
}


def state_for(stage):
    return STATES[Stage(stage)]
