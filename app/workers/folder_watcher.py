import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from ..config import Settings
from ..database import SessionLocal
from ..models.job import Job

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".bmp"}


class OCREventHandler(FileSystemEventHandler):
    def __init__(self, settings: Settings, process_fn, loop: asyncio.AbstractEventLoop):
        self._settings = settings
        self._process_fn = process_fn
        self._loop = loop
        self._in_flight: set[str] = set()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="watcher")

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return
        key = str(path)
        if key in self._in_flight:
            return
        self._in_flight.add(key)
        asyncio.run_coroutine_threadsafe(self._handle(path), self._loop)

    async def _handle(self, path: Path) -> None:
        await asyncio.sleep(0.5)  # brief wait for file write to complete
        try:
            job_id = self._create_job(path)
            await asyncio.get_running_loop().run_in_executor(
                self._executor, self._process_fn, job_id
            )
        except Exception:
            logger.exception("Folder watcher failed processing %s", path)
        finally:
            self._in_flight.discard(str(path))

    def _create_job(self, path: Path) -> str:
        job_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            job = Job(
                id=job_id,
                filename=path.name,
                source="folder",
                status="pending",
                processing_mode=self._settings.watch_default_mode,
                output_format=self._settings.watch_default_format,
                file_path=str(path),
                created_at=datetime.utcnow(),
            )
            db.add(job)
            db.commit()
        finally:
            db.close()
        return job_id


class WatchdogWatcher:
    def __init__(self, settings: Settings, process_fn):
        self._settings = settings
        self._process_fn = process_fn
        self._observer: Observer | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        watch_dir = Path(self._settings.watch_input_dir)
        watch_dir.mkdir(parents=True, exist_ok=True)
        handler = OCREventHandler(self._settings, self._process_fn, loop)
        self._observer = Observer()
        self._observer.schedule(handler, str(watch_dir), recursive=False)
        self._observer.start()
        logger.info("Folder watcher started on %s", watch_dir)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("Folder watcher stopped")
