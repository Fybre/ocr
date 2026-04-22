import io
import json as _json
import logging
from datetime import datetime
from pathlib import Path

import PIL.Image
from sqlalchemy.orm import Session

from ..config import Settings
from ..models.job import Job
from ..ocr.auto_detector import AutoDetector, build_llm_engine
from ..ocr.tesseract_engine import TesseractEngine
from ..ocr.base import OCREngine, PageResult
from .pdf_renderer import PDFRenderer
from .image_preprocessor import ImagePreprocessor
from .formatter import OCRFormatter

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".bmp"}
THUMBNAIL_WIDTH = 1200


class OCRProcessor:
    def __init__(self, settings: Settings, db: Session):
        self._settings = settings
        self._db = db
        self._renderer = PDFRenderer()
        self._preprocessor = ImagePreprocessor()
        self._formatter = OCRFormatter()

    def process(self, job_id: str) -> None:
        job: Job | None = self._db.get(Job, job_id)
        if job is None:
            logger.error("Job %s not found", job_id)
            return

        job.status = "processing"
        job.started_at = datetime.utcnow()
        self._db.commit()

        try:
            self._run(job)
        except Exception as exc:
            logger.exception("Processing failed for job %s", job_id)
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.utcnow()
            self._db.commit()

    def _run(self, job: Job) -> None:
        file_path = Path(job.file_path)
        suffix = file_path.suffix.lower()

        # 1. Render to images
        if suffix == ".pdf":
            images = self._renderer.render(file_path, dpi=self._settings.ocr_dpi)
        elif suffix in SUPPORTED_IMAGE_SUFFIXES:
            images = [PIL.Image.open(file_path)]
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

        if not images:
            raise ValueError("No pages found in document")

        job.page_count = len(images)
        self._db.commit()

        # 2. Preprocess
        images = self._preprocessor.process_all(images)

        # 3. Save thumbnails (async-friendly: saves to disk)
        thumb_dir = Path(self._settings.upload_dir) / job.id / "thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        for i, img in enumerate(images, start=1):
            thumb = _make_thumbnail(img, THUMBNAIL_WIDTH)
            thumb.save(thumb_dir / f"page_{i}.jpg", format="JPEG", quality=80)

        # 4. Select engine (also classifies content type in auto mode)
        engine, content_type = self._select_engine(job, images[0])
        job.detected_content_type = content_type
        self._db.commit()

        # 5. OCR each page
        results: list[PageResult] = []
        for i, img in enumerate(images, start=1):
            result = engine.process(
                img,
                page_num=i,
                mode=job.processing_mode,
                output_format=job.output_format,
                languages=job.languages or "eng",
            )
            results.append(result)

        # 6. Format
        formatted = self._formatter.format(results, job.output_format)

        # 7. Persist
        job.result_text = formatted
        job.engine_used = engine.name
        confs = [r.confidence for r in results if r.confidence is not None]
        job.confidence_score = float(sum(confs) / len(confs)) if confs else None
        job.status = "done"
        job.completed_at = datetime.utcnow()

        all_boxes = {
            str(r.page_num): [
                {"text": b.text, "conf": b.confidence,
                 "x": round(b.x, 5), "y": round(b.y, 5),
                 "w": round(b.w, 5), "h": round(b.h, 5)}
                for b in r.bounding_boxes
            ]
            for r in results if r.bounding_boxes
        }
        job.bounding_boxes_json = _json.dumps(all_boxes) if all_boxes else None

        # 8. Write result file (folder watcher jobs)
        if job.source == "folder":
            ext = ".md" if job.output_format == "markdown" else ".txt"
            stem = Path(job.filename).stem
            out_dir = Path(self._settings.watch_output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            result_path = out_dir / f"{stem}{ext}"
            result_path.write_text(formatted, encoding="utf-8")
            job.result_path = str(result_path)

            meta = {
                "job_id": job.id,
                "engine_used": job.engine_used,
                "confidence_score": job.confidence_score,
                "page_count": job.page_count,
                "processing_mode": job.processing_mode,
                "completed_at": job.completed_at.isoformat(),
            }
            (out_dir / f"{stem}.meta.json").write_text(_json.dumps(meta, indent=2), encoding="utf-8")

        self._db.commit()

    def _select_engine(self, job: Job, first_page: PIL.Image.Image) -> tuple[OCREngine, str]:
        """Returns (engine, detected_content_type)."""
        llm_provider = job.llm_provider or "auto"
        languages = job.languages or "eng"
        mode = job.processing_mode

        if mode == "handwriting":
            llm = build_llm_engine(self._settings, llm_provider)
            if llm:
                return llm, "handwritten"
            logger.warning("No LLM engine available; falling back to Tesseract")
            return TesseractEngine(), "handwritten"

        if mode == "image_description":
            llm = build_llm_engine(self._settings, llm_provider)
            if llm:
                return llm, "image"
            return TesseractEngine(), "image"

        if mode == "machine":
            return TesseractEngine(), "printed"

        # auto — use classifier-aware AutoDetector
        detector = AutoDetector(self._settings, llm_provider=llm_provider)
        engine, content_type = detector.select_engine(first_page, languages=languages)
        return engine, content_type


def _make_thumbnail(image: PIL.Image.Image, width: int) -> PIL.Image.Image:
    ratio = width / image.width
    height = int(image.height * ratio)
    return image.resize((width, height), PIL.Image.LANCZOS)
