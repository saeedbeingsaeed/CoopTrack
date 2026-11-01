# Memento pattern (not covered in class).
# Reference: https://refactoring.guru/design-patterns/memento
#
# - Originator: Application. It makes a StageMemento of itself before a move
#   and restores itself from one on undo.
# - Memento: StageMemento. A snapshot of what a move changes (stage and applied
#   date). Only Application reads what's inside.
# - Caretaker: UndoHistory. Keeps a stack of mementos per application and hands
#   back the newest one, without looking inside.
#
# Web requests and CLI commands don't share memory, so the stack lives in the
# StageSnapshot table. That's also why a move made on the website can be undone
# from the CLI and the other way round.

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class StageMemento:
    _stage: int
    _date_applied: datetime.date | None

    def serialize(self):
        date = self._date_applied.isoformat() if self._date_applied else None
        return json.dumps({"stage": self._stage, "date_applied": date})

    @classmethod
    def deserialize(cls, data):
        raw = json.loads(data)
        date = datetime.date.fromisoformat(raw["date_applied"]) if raw["date_applied"] else None
        return cls(raw["stage"], date)


class UndoHistory:
    LIMIT = 10  # nobody needs to undo more than this

    def __init__(self, application):
        self._application = application

    def push(self, memento):
        from tracker.models import StageSnapshot

        StageSnapshot.objects.create(application=self._application, data=memento.serialize())
        old = list(self._snapshots().values_list("pk", flat=True)[self.LIMIT :])
        StageSnapshot.objects.filter(pk__in=old).delete()

    def pop(self):
        newest = self._snapshots().first()
        if newest is None:
            return None
        newest.delete()
        return StageMemento.deserialize(newest.data)

    def can_undo(self):
        return self._snapshots().exists()

    def _snapshots(self):
        from tracker.models import StageSnapshot

        return StageSnapshot.objects.filter(application=self._application).order_by("-created_at", "-pk")
