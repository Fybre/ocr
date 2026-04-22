import base64
import io
import logging
import re
from typing import Literal

import PIL.Image
from openai import OpenAI

logger = logging.getLogger(__name__)

ContentType = Literal["printed", "handwritten", "mixed", "unknown"]

CLASSIFY_PROMPT = (
    "Look at this document image and classify the text.\n"
    "Reply with exactly one word — no explanation, no punctuation:\n"
    "  printed     (typed or machine-generated text)\n"
    "  handwritten (text written by hand)\n"
    "  mixed       (significant amounts of both)\n"
    "One word only."
)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _unwrap_thinking(text: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models (e.g. qwen3)."""
    return _THINK_RE.sub("", text).strip()


def _image_to_base64(image: PIL.Image.Image) -> str:
    buf = io.BytesIO()
    # Resize for classification — full resolution not needed, saves tokens/latency
    thumb = image.copy()
    thumb.thumbnail((1024, 1024), PIL.Image.LANCZOS)
    thumb.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


class ContentClassifier:
    """
    Uses a local vision model (Ollama) to classify document content as printed,
    handwritten, or mixed before OCR engine selection.

    Falls back gracefully if no local model is available.
    """

    def __init__(self, base_url: str, model: str):
        self._client = OpenAI(base_url=base_url, api_key="ollama")
        self._model = model

    def classify(self, image: PIL.Image.Image) -> ContentType:
        try:
            b64 = _image_to_base64(image)
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "/no_think"},
                    {"role": "user", "content": [
                        {"type": "text", "text": CLASSIFY_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ]},
                ],
                max_tokens=50,
                temperature=0,
            )
            msg = response.choices[0].message
            # qwen3-vl puts thinking in 'reasoning' and leaves 'content' empty
            content = msg.content or ""
            reasoning = (getattr(msg, "model_extra", None) or {}).get("reasoning") or ""
            raw = _unwrap_thinking(content).lower() or reasoning.lower()
            for label in ("handwritten", "mixed", "printed"):
                if label in raw:
                    logger.info("Content classified as '%s'", label)
                    return label  # type: ignore[return-value]
            logger.warning("Classifier unrecognised response (content=%r reasoning=%r)", content[:80], reasoning[:80])
            return "unknown"
        except Exception as exc:
            logger.warning("Content classification failed: %s", exc)
            return "unknown"
