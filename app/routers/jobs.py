import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..auth.dependencies import verify_api_key
from ..config import settings
from ..database import get_db, SessionLocal
from ..models.api_key import ApiKey
from ..models.job import Job
from ..pipeline.processor import OCRProcessor
from ..schemas.job import (
    JobReprocess, JobResponse, JobResultResponse, JobListResponse,
)
from ..webhooks.dispatcher import dispatcher
from ..workers import job_queue

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

ALLOWED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".bmp"}


def _save_upload(upload: UploadFile, job_id: str) -> tuple[str, str]:
    suffix = Path(upload.filename or "file").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
    dest = Path(settings.upload_dir) / f"{job_id}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(upload.file.read())
    return str(dest), upload.filename or f"file{suffix}"


def _process_sync(job_id: str) -> None:
    db = SessionLocal()
    try:
        proc = OCRProcessor(settings, db)
        proc.process(job_id)

        job = db.get(Job, job_id)
        if job and job.webhook_url and job.status == "done":
            asyncio.run(dispatcher.dispatch(job, db))
    finally:
        db.close()



@router.post("", response_model=JobResultResponse, status_code=201)
async def submit_job(
    file: UploadFile = File(...),
    mode: str = Form("auto"),
    output_format: str = Form("plain"),
    async_mode: bool = Form(False),
    webhook_url: str | None = Form(None),
    llm_provider: str = Form("auto"),
    languages: str = Form("eng"),
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> JobResultResponse:
    job_id = str(uuid.uuid4())
    file_path, filename = _save_upload(file, job_id)
    source = "api_async" if async_mode else "api_sync"

    job = Job(
        id=job_id,
        filename=filename,
        source=source,
        status="pending",
        processing_mode=mode,
        output_format=output_format,
        languages=languages,
        llm_provider=llm_provider,
        webhook_url=webhook_url,
        webhook_status="pending" if webhook_url else None,
        file_path=file_path,
        created_at=datetime.utcnow(),
        api_key_id=api_key.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if async_mode:
        await job_queue.enqueue(job_id)
        return JobResultResponse.model_validate(job)

    # Synchronous: process inline (in thread to avoid blocking event loop)
    await asyncio.get_event_loop().run_in_executor(None, _process_sync, job_id)
    db.refresh(job)

    # Fire webhook in background if needed
    if job.webhook_url and job.status == "done":
        asyncio.create_task(dispatcher.dispatch(job, db))

    return JobResultResponse.model_validate(job)


@router.get("", response_model=JobListResponse)
def list_jobs(
    status: str | None = None,
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> JobListResponse:
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    if source:
        query = query.filter(Job.source == source)
    total = query.count()
    items = query.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()
    return JobListResponse(
        items=[JobResponse.model_validate(j) for j in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobResultResponse)
def get_job(
    job_id: str,
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> JobResultResponse:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResultResponse.model_validate(job)


@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_job_result(
    job_id: str,
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> JobResultResponse:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("done", "failed"):
        raise HTTPException(status_code=202, detail="Job not yet complete")
    return JobResultResponse.model_validate(job)


@router.get("/{job_id}/download")
def download_result(
    job_id: str,
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done" or not job.result_text:
        raise HTTPException(status_code=400, detail="Result not available")

    ext = "md" if job.output_format == "markdown" else "txt"
    stem = Path(job.filename).stem
    media_type = "text/markdown" if job.output_format == "markdown" else "text/plain"
    content = job.result_text.encode("utf-8")

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{stem}.{ext}"'},
    )


@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> None:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Delete associated files
    _delete_file(job.file_path)
    if job.result_path:
        _delete_file(job.result_path)
    # Delete thumbnails
    thumb_dir = Path(settings.upload_dir) / job.id / "thumbs"
    if thumb_dir.exists():
        import shutil
        shutil.rmtree(thumb_dir, ignore_errors=True)
    db.delete(job)
    db.commit()


@router.post("/{job_id}/reprocess", response_model=JobResultResponse, status_code=201)
async def reprocess_job(
    job_id: str,
    params: JobReprocess,
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> JobResultResponse:
    original = db.get(Job, job_id)
    if not original:
        raise HTTPException(status_code=404, detail="Job not found")
    if not Path(original.file_path).exists():
        raise HTTPException(status_code=400, detail="Original file no longer available")

    new_id = str(uuid.uuid4())
    new_job = Job(
        id=new_id,
        filename=original.filename,
        source="api_sync",
        status="pending",
        processing_mode=params.mode or original.processing_mode,
        output_format=params.output_format or original.output_format,
        languages=params.languages or original.languages or "eng",
        llm_provider=params.llm_provider or "auto",
        file_path=original.file_path,
        webhook_url=original.webhook_url,
        created_at=datetime.utcnow(),
        api_key_id=api_key.id,
    )
    db.add(new_job)
    db.commit()

    await asyncio.get_event_loop().run_in_executor(None, _process_sync, new_id)
    db.refresh(new_job)
    return JobResultResponse.model_validate(new_job)


def _delete_file(path: str | None) -> None:
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
