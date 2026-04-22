import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import create_tables, SessionLocal
from .models.job import Job
from .pipeline.processor import OCRProcessor
from .webhooks.dispatcher import dispatcher
from .workers.folder_watcher import WatchdogWatcher
from .workers import job_queue
from .routers import jobs, keys, ui

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create data directories before any mounts reference them
settings.ensure_dirs()


def _make_process_fn():
    """Returns a sync function that creates its own DB session and processes a job."""
    def process(job_id: str) -> None:
        db = SessionLocal()
        try:
            proc = OCRProcessor(settings, db)
            proc.process(job_id)
            job = db.get(Job, job_id)
            if job and job.webhook_url and job.status == "done":
                asyncio.run(dispatcher.dispatch(job, db))
        finally:
            db.close()
    return process


_watcher: WatchdogWatcher | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_tables()
    dispatcher.set_base_url(settings.app_base_url)

    process_fn = _make_process_fn()

    # Start async job queue worker
    worker_task = asyncio.create_task(job_queue.worker_loop(process_fn))

    # Start folder watcher
    global _watcher
    _watcher = WatchdogWatcher(settings, process_fn)
    _watcher.start(asyncio.get_event_loop())

    # Start retention cleanup background task
    cleanup_task = asyncio.create_task(_retention_loop())

    logger.info("OCR service started — version %s", settings.app_version)
    yield

    # Shutdown
    if _watcher:
        _watcher.stop()
    worker_task.cancel()
    cleanup_task.cancel()
    logger.info("OCR service stopped")


app = FastAPI(
    title="OCR Document Processing",
    version=settings.app_version,
    lifespan=lifespan,
)

# Static files
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

# Routers
app.include_router(jobs.router)
app.include_router(keys.router)
app.include_router(ui.router)


@app.get("/health", tags=["system"])
def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "engines": {
            "tesseract": _check_tesseract(),
            "paddle": True,
            "openai": settings.has_openai,
            "azure": settings.has_azure,
            "local_llm": settings.has_local_llm,
        },
    }


def _check_tesseract() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(3600)  # check every hour
        _run_retention()


def _run_retention() -> None:
    if settings.job_retention_days <= 0:
        return
    cutoff = datetime.utcnow() - timedelta(days=settings.job_retention_days)
    db = SessionLocal()
    try:
        old_jobs = db.query(Job).filter(Job.created_at < cutoff).all()
        for job in old_jobs:
            _delete_file(job.file_path)
            if job.result_path:
                _delete_file(job.result_path)
            thumb_dir = Path(settings.upload_dir) / job.id / "thumbs"
            if thumb_dir.exists():
                import shutil
                shutil.rmtree(thumb_dir, ignore_errors=True)
            db.delete(job)
        db.commit()
        if old_jobs:
            logger.info("Retention cleanup: deleted %d old jobs", len(old_jobs))
    finally:
        db.close()


def _delete_file(path: str | None) -> None:
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
