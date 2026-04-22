import json
import logging
import PIL.Image
from openai import OpenAI
from .openai_engine import (
    OpenAIVisionEngine, _image_to_base64, _format_description,
    OCR_PROMPT, OCR_MARKDOWN_PROMPT, IMAGE_DESCRIPTION_PROMPT,
)
from .base import PageResult

logger = logging.getLogger(__name__)


_COMMENTARY_PREFIXES = (
    "got it", "sure,", "sure!", "of course", "certainly", "absolutely",
    "let me", "let's", "i'll", "i will", "i can see", "i see",
    "here is", "here's", "below is", "the image", "this image",
    "looking at", "in this image", "the document", "this document",
    "first,", "first let", "now,", "alright",
)


def _strip_commentary(text: str) -> str:
    """Remove common LLM preamble lines that aren't part of the document text."""
    lines = text.splitlines()
    out = []
    for line in lines:
        low = line.strip().lower()
        if any(low.startswith(p) for p in _COMMENTARY_PREFIXES):
            continue
        out.append(line)
    return "\n".join(out)


def _message_text(message) -> str:
    """Extract text from an Ollama response message.

    qwen3-vl (and other reasoning models) put their output in a 'reasoning'
    field and leave 'content' empty. Fall back to 'reasoning' when that happens.
    """
    content = message.content or ""
    if content:
        return content
    extra = (getattr(message, "model_extra", None) or {})
    return extra.get("reasoning") or ""


_MAX_LOCAL_IMAGE_PX = 1568  # keeps token count manageable for local models


_CLEANUP_PROMPT = (
    "Extract only the document text from the following OCR notes. "
    "Remove all commentary, meta-text, and analysis. "
    "Output only the actual text that appears in the document, preserving its structure and line breaks."
)


class LocalVisionEngine(OpenAIVisionEngine):
    """Ollama or any OpenAI-compatible local vision model."""

    def __init__(self, base_url: str, model: str, cleanup_model: str | None = None):
        self._client = OpenAI(base_url=base_url, api_key="ollama")
        self._model = model
        self._cleanup_model = cleanup_model

    @property
    def name(self) -> str:
        return f"LocalVisionEngine({self._model})"

    def process(
        self,
        image: PIL.Image.Image,
        page_num: int = 1,
        mode: str = "auto",
        output_format: str = "plain",
        languages: str = "eng",
    ) -> PageResult:
        img = image.copy()
        img.thumbnail((_MAX_LOCAL_IMAGE_PX, _MAX_LOCAL_IMAGE_PX), PIL.Image.LANCZOS)
        return super().process(img, page_num, mode, output_format, languages)

    def _extract(self, image: PIL.Image.Image, page_num: int, prompt: str) -> PageResult:
        try:
            b64 = _image_to_base64(image)
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "/no_think"},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ]},
                ],
                max_tokens=4096,
                temperature=0,
            )
            raw = _message_text(response.choices[0].message).strip()

            if self._cleanup_model and raw:
                raw = self._cleanup(raw)

            text = _strip_commentary(raw).strip()
            return PageResult(page_num=page_num, text=text, confidence=None)
        except Exception as exc:
            logger.error("Local LLM extraction failed on page %d: %s", page_num, exc)
            return PageResult(page_num=page_num, text="", confidence=None)

    def _cleanup(self, raw: str) -> str:
        """Pass vision model output through a text model to strip thinking commentary."""
        try:
            response = self._client.chat.completions.create(
                model=self._cleanup_model,
                messages=[
                    {"role": "system", "content": "/no_think"},
                    {"role": "user", "content": f"{_CLEANUP_PROMPT}\n\n---\n{raw}\n---"},
                ],
                max_tokens=4096,
                temperature=0,
            )
            cleaned = _message_text(response.choices[0].message).strip()
            return cleaned if cleaned else raw
        except Exception as exc:
            logger.warning("Cleanup step failed, using raw output: %s", exc)
            return raw

    def _describe(self, image: PIL.Image.Image, page_num: int) -> PageResult:
        try:
            b64 = _image_to_base64(image)
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "/no_think"},
                    {"role": "user", "content": [
                        {"type": "text", "text": IMAGE_DESCRIPTION_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ]},
                ],
                max_tokens=1024,
            )
            raw = _message_text(response.choices[0].message)
            try:
                data = json.loads(raw.strip().lstrip("```json").rstrip("```"))
                text = _format_description(data)
            except Exception:
                text = raw.strip()
            return PageResult(page_num=page_num, text=text, confidence=None)
        except Exception as exc:
            logger.error("Local LLM description failed on page %d: %s", page_num, exc)
            return PageResult(page_num=page_num, text="", confidence=None)
