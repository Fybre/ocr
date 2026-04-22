import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import settings
from ..database import SessionLocal
from ..models.job import Job
from ..workers.job_queue import enqueue

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

ALLOWED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".bmp"}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {
        "request": request,
        "has_local": settings.has_local_llm,
        "has_openai": settings.has_openai,
        "has_azure": settings.has_azure,
    })


@router.post("/upload")
async def web_upload(
    file: UploadFile = File(...),
    mode: str = Form("auto"),
    output_format: str = Form("plain"),
    llm_provider: str = Form("auto"),
    languages: str = Form("eng"),
) -> RedirectResponse:
    suffix = Path(file.filename or "file").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    job_id = str(uuid.uuid4())
    dest = Path(settings.upload_dir) / f"{job_id}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(file.file.read())

    db = SessionLocal()
    try:
        job = Job(
            id=job_id,
            filename=file.filename or f"file{suffix}",
            source="upload",
            status="pending",
            processing_mode=mode,
            output_format=output_format,
            languages=languages,
            llm_provider=llm_provider,
            file_path=str(dest),
            created_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()
    finally:
        db.close()

    await enqueue(job_id)
    return RedirectResponse(url=f"/view/{job_id}", status_code=303)


@router.get("/view/{job_id}", response_class=HTMLResponse)
async def view_result(request: Request, job_id: str) -> HTMLResponse:
    import json as _json
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        bboxes: dict = {}
        if job.bounding_boxes_json:
            try:
                bboxes = _json.loads(job.bounding_boxes_json)
            except Exception:
                pass
        return templates.TemplateResponse("result.html", {
            "request": request,
            "job": job,
            "page_count": job.page_count or 1,
            "bounding_boxes": bboxes,
        })
    finally:
        db.close()


@router.get("/view/{job_id}/download")
async def web_download(job_id: str):
    """Unauthenticated download endpoint used by the web result page."""
    from fastapi.responses import StreamingResponse
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job or job.status != "done" or not job.result_text:
            raise HTTPException(status_code=404, detail="Result not available")
        ext = "md" if job.output_format == "markdown" else "txt"
        stem = Path(job.filename).stem
        media_type = "text/markdown" if job.output_format == "markdown" else "text/plain"
        content = job.result_text.encode("utf-8")
        return StreamingResponse(
            iter([content]),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{stem}.{ext}"'},
        )
    finally:
        db.close()


@router.get("/view/{job_id}/status")
async def job_status(job_id: str) -> dict:
    """Unauthenticated status endpoint used by the web result page."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"status": job.status}
    finally:
        db.close()




