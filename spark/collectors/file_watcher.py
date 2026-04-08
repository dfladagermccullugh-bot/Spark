"""Watch project and knowledge folders for file changes."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from spark.db.connection import get_session
from spark.db.models import ActivityEvent, EventType, Project

logger = logging.getLogger(__name__)

# Ignore these patterns in file watching
IGNORE_PATTERNS = {
    ".git",
    "__pycache__",
    ".pyc",
    "node_modules",
    ".DS_Store",
    ".ruff_cache",
    ".pytest_cache",
    ".venv",
    "venv",
}


class ProjectFileHandler(FileSystemEventHandler):
    """Handle file changes in project directories."""

    def __init__(self, on_change: Callable[[str, str], None] | None = None):
        self._on_change = on_change

    def _should_ignore(self, path: str) -> bool:
        parts = Path(path).parts
        return any(part in IGNORE_PATTERNS or part.endswith(".pyc") for part in parts)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._should_ignore(event.src_path):
            return
        self._record_event(event.src_path, "modified")

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._should_ignore(event.src_path):
            return
        self._record_event(event.src_path, "created")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._should_ignore(event.src_path):
            return
        self._record_event(event.src_path, "deleted")

    def _record_event(self, file_path: str, action: str) -> None:
        logger.debug(f"File {action}: {file_path}")

        # Find which project this file belongs to
        try:
            with get_session() as session:
                projects = session.query(Project).all()
                for project in projects:
                    if file_path.startswith(project.local_path):
                        relative = str(Path(file_path).relative_to(project.local_path))
                        event = ActivityEvent(
                            project_id=project.id,
                            event_type=EventType.FILE_CHANGE.value,
                            event_data={"file": relative, "action": action},
                            occurred_at=datetime.utcnow(),
                        )
                        session.add(event)
                        project.last_activity_at = datetime.utcnow()
                        break
        except Exception as e:
            logger.warning(f"Error recording file event: {e}")

        if self._on_change:
            self._on_change(file_path, action)


class KnowledgeFileHandler(FileSystemEventHandler):
    """Handle new files dropped into the knowledge folder."""

    def __init__(self, on_new_knowledge: Callable[[str], None] | None = None):
        self._on_new_knowledge = on_new_knowledge

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        logger.info(f"New knowledge item: {event.src_path}")
        if self._on_new_knowledge:
            self._on_new_knowledge(event.src_path)


class SparkFileWatcher:
    """Manage file watchers for project and knowledge directories."""

    def __init__(
        self,
        projects_dir: Path,
        knowledge_dir: Path,
        on_project_change: Callable[[str, str], None] | None = None,
        on_new_knowledge: Callable[[str], None] | None = None,
    ):
        self._observer = Observer()
        self._projects_dir = projects_dir
        self._knowledge_dir = knowledge_dir

        project_handler = ProjectFileHandler(on_change=on_project_change)
        knowledge_handler = KnowledgeFileHandler(on_new_knowledge=on_new_knowledge)

        if projects_dir.exists():
            self._observer.schedule(project_handler, str(projects_dir), recursive=True)
        if knowledge_dir.exists():
            self._observer.schedule(knowledge_handler, str(knowledge_dir), recursive=True)

    def start(self) -> None:
        self._observer.start()
        logger.info(
            f"Watching: projects={self._projects_dir}, knowledge={self._knowledge_dir}"
        )

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
