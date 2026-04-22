import logging
import PIL.Image
from .base import OCREngine
from .classifier import ContentClassifier, ContentType
from .tesseract_engine import TesseractEngine

logger = logging.getLogger(__name__)


def build_llm_engine(settings, llm_provider: str = "auto") -> OCREngine | None:
    """Instantiate the appropriate LLM vision engine based on provider preference and config."""
    from .openai_engine import OpenAIVisionEngine
    from .azure_engine import AzureVisionEngine
    from .local_engine import LocalVisionEngine

    if llm_provider == "local" or (llm_provider == "auto" and settings.has_local_llm):
        return LocalVisionEngine(
            base_url=settings.local_llm_base_url,
            model=settings.local_llm_model,
            cleanup_model=settings.local_cleanup_model.strip() or None,
        )
    if llm_provider == "azure" or (llm_provider == "auto" and settings.has_azure):
        return AzureVisionEngine(
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            deployment=settings.azure_openai_deployment,
        )
    if llm_provider == "openai" or (llm_provider == "auto" and settings.has_openai):
        return OpenAIVisionEngine(api_key=settings.openai_api_key)
    return None


def build_classifier(settings) -> ContentClassifier | None:
    """Return a ContentClassifier if a local vision model is configured."""
    if not settings.has_local_llm:
        return None
    model = settings.effective_classifier_model
    if not model:
        logger.warning("No classifier model resolved; skipping content classification")
        return None
    return ContentClassifier(base_url=settings.local_llm_base_url, model=model)


class AutoDetector:
    """
    Selects the best OCR engine for auto mode.

    Strategy:
    1. If a local vision model is available, classify content type first
       (printed / handwritten / mixed / unknown). Route directly based on result.
    2. If classification is unknown, fall back to Tesseract confidence scoring:
       high → Tesseract, low → LLM.
    """

    def __init__(self, settings, llm_provider: str = "auto"):
        self._threshold = settings.ocr_confidence_threshold
        self._tesseract = TesseractEngine()
        self._llm = build_llm_engine(settings, llm_provider)
        self._classifier = build_classifier(settings)

    def classify(self, image: PIL.Image.Image) -> ContentType:
        """Run content classification. Returns 'unknown' if no classifier is available."""
        if self._classifier is None:
            return "unknown"
        return self._classifier.classify(image)

    def select_engine(
        self, first_page: PIL.Image.Image, languages: str = "eng"
    ) -> tuple[OCREngine, ContentType]:
        """Returns (chosen_engine, detected_content_type)."""
        content_type = self.classify(first_page)

        if content_type == "handwritten":
            engine = self._llm or self._tesseract
            logger.info("Classified as handwritten → %s", engine.name)
            return engine, content_type

        if content_type == "printed":
            logger.info("Classified as printed → TesseractEngine")
            return self._tesseract, content_type

        if content_type == "mixed":
            engine = self._llm or self._tesseract
            logger.info("Classified as mixed content → %s", engine.name)
            return engine, content_type

        # content_type == "unknown": fall back to confidence-based selection
        logger.info("Classification unknown, falling back to Tesseract confidence scoring")
        tess_conf = self._tesseract.get_confidence(first_page, languages=languages)
        logger.info("Tesseract confidence: %.1f (threshold: %.1f)", tess_conf, self._threshold)
        if tess_conf >= self._threshold or self._llm is None:
            logger.info("Using TesseractEngine (confidence %.1f)", tess_conf)
            return self._tesseract, content_type
        logger.info("Low Tesseract confidence (%.1f) → LLM engine", tess_conf)
        return self._llm, content_type
