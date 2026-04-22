import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from ..models.job import Job

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BASE_DELAY = 2
TIMEOUT = 10


class WebhookDispatcher:
    async def dispatch(self, job: Job, db: Session) -> None:
        if not job.webhook_url:
            return

        payload = {
            "event": "job.completed",
            "job_id": job.id,
            "status": job.status,
            "filename": job.filename,
            "engine_used": job.engine_used,
            "processing_mode": job.processing_mode,
            "output_format": job.output_format,
            "page_count": job.page_count,
            "confidence_score": job.confidence_score,
            "result_url": f"{self._base_url}/api/v1/jobs/{job.id}/result",
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                    resp = await client.post(job.webhook_url, json=payload)
                    resp.raise_for_status()
                job.webhook_status = "delivered"
                job.webhook_attempts = attempt
                db.commit()
                logger.info("Webhook delivered for job %s on attempt %d", job.id, attempt)
                return
            except Exception as exc:
                logger.warning(
                    "Webhook attempt %d/%d failed for job %s: %s",
                    attempt, MAX_ATTEMPTS, job.id, exc,
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(BASE_DELAY * (2 ** (attempt - 1)))

        job.webhook_status = "failed"
        job.webhook_attempts = MAX_ATTEMPTS
        db.commit()
        logger.error("Webhook permanently failed for job %s after %d attempts", job.id, MAX_ATTEMPTS)

    def set_base_url(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def __init__(self, base_url: str = "http://localhost:8000"):
        self._base_url = base_url.rstrip("/")


dispatcher = WebhookDispatcher()
