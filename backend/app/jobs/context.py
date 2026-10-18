"""Contexto que reciben los handlers de jobs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from . import queue


class Cancelled(Exception):
    pass


@dataclass
class JobContext:
    db: Session
    job_id: int
    user_id: int
    log_file: Path

    def log(self, message: str) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(message.rstrip("\n") + "\n")

    def progress(self, value: int) -> None:
        queue.set_progress(self.db, self.job_id, value)

    def check_cancelled(self) -> None:
        if queue.is_cancelled(self.db, self.job_id):
            raise Cancelled()
