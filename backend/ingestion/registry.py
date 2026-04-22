import uuid
from dataclasses import dataclass
from typing import Literal


@dataclass
class IngestStatus:
    status: Literal["pending", "complete", "error"]
    chunks_stored: int | None = None
    error_msg: str | None = None


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, IngestStatus] = {}

    def create(self) -> str:
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = IngestStatus(status="pending")
        return task_id

    def update(self, task_id: str, **kwargs) -> None:
        if task_id not in self._tasks:
            return
        status = self._tasks[task_id]
        for key, value in kwargs.items():
            setattr(status, key, value)

    def get(self, task_id: str) -> IngestStatus | None:
        return self._tasks.get(task_id)


registry = TaskRegistry()
