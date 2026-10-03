"""Async task processing for long-running geometry operations."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from flask import current_app


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    name: str
    func: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    project_id: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "project_id": self.project_id,
        }


class TaskQueue:
    """Thread-safe task queue with background worker pool."""

    def __init__(self, app: Any = None, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()
        self._max_workers = max_workers
        self._app = app

    def submit(self, name: str, func: Callable, *args, project_id: str = "", **kwargs) -> str:
        """Submit a task for async execution. Returns task ID."""
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            id=task_id,
            name=name,
            func=func,
            args=args,
            kwargs=kwargs,
            project_id=project_id,
        )

        with self._lock:
            self._tasks[task_id] = task

        # Submit to executor
        future = self._executor.submit(self._run_task, task)
        task._future = future  # type: ignore

        return task_id

    def _run_task(self, task: Task) -> None:
        with self._lock:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(timezone.utc)

        try:
            if self._app is not None:
                with self._app.app_context():
                    result = task.func(*task.args, **task.kwargs)
            else:
                result = task.func(*task.args, **task.kwargs)
            with self._lock:
                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            with self._lock:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = datetime.now(timezone.utc)
            try:
                current_app.logger.exception("Task %s failed: %s", task.id, e)
            except RuntimeError:
                pass

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_tasks_for_project(self, project_id: str) -> list[Task]:
        """Get all tasks for a project."""
        with self._lock:
            return [t for t in self._tasks.values() if t.project_id == project_id]

    def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> Optional[Task]:
        """Wait for task to complete."""
        task = self.get_task(task_id)
        if not task:
            return None
        if hasattr(task, '_future'):
            task._future.result(timeout=timeout)  # type: ignore
        return self.get_task(task_id)

    def cleanup_completed(self, max_age_seconds: int = 3600) -> int:
        """Remove completed tasks older than max_age_seconds."""
        now = datetime.now(timezone.utc)
        removed = 0
        with self._lock:
            to_remove = [
                tid for tid, task in self._tasks.items()
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                and task.completed_at
                and (now - task.completed_at).total_seconds() > max_age_seconds
            ]
            for tid in to_remove:
                del self._tasks[tid]
                removed += 1
        return removed

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the executor."""
        self._executor.shutdown(wait=wait)


# Global task queue instance
_task_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    """Get the global task queue instance."""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue


def init_task_queue(app: Any = None, max_workers: int = 2) -> None:
    """Initialize the global task queue (holds the Flask app for worker context)."""
    global _task_queue
    _task_queue = TaskQueue(app, max_workers=max_workers)


def submit_async_task(name: str, func: Callable, *args, project_id: str = "", **kwargs) -> str:
    """Convenience function to submit an async task."""
    return get_task_queue().submit(name, func, *args, project_id=project_id, **kwargs)


def get_task_status(task_id: str) -> Optional[dict]:
    """Get task status as dict."""
    task = get_task_queue().get_task(task_id)
    return task.to_dict() if task else None


def get_project_tasks(project_id: str) -> list[dict]:
    """Get all tasks for a project as dicts."""
    return [t.to_dict() for t in get_task_queue().get_tasks_for_project(project_id)]