import base64
import io
import json
import logging
import PIL.Image
from openai import OpenAI
from .base import OCREngine, PageResult

logger = logging.getLogger(__name__)

OCR_PROMPT = (
    "Transcribe every word visible in this image.\n"
    "Rules:\n"
    "- Output ONLY the transcribed text, nothing else.\n"
    "- Do NOT explain, describe, or comment.\n"
    "- Do NOT use phrases like 'Got it', 'Here is', 'The image shows', 'Let me', etc.\n"
    "- Preserve line breaks and paragraph structure.\n"
    "Start transcribing immediately."
)

OCR_MARKDOWN_PROMPT = (
    "Transcribe every word visible in this image and format as Markdown.\n"
    "Rules:\n"
    "- Output ONLY the Markdown transcription, nothing else.\n"
    "- Do NOT explain, describe, or comment.\n"
    "- Do NOT use phrases like 'Got it', 'Here is', 'The image shows', 'Let me', etc.\n"
    "- Use headings, lists, and tables where appropriate.\n"
    "Start transcribing immediately."
)

IMAGE_DESCRIPTION_PROMPT = (
    "Analyze this image and return a JSON object with these fields:\n"
    '- "title": a short descriptive title (max 10 words)\n'
    '- "summary": a 2-3 sentence description of the image content\n'
    '- "key_elements": a list of the main visual elements or subjects\n'
    '- "detected_text": any visible text in the image, or null if none\n'
    "Return only valid JSON, no markdown code fences."
)


def _image_to_base64(image: PIL.Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


class OpenAIVisionEngine(OCREngine):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return f"OpenAIVisionEngine({self._model})"

    @property
    def supports_confidence(self) -> bool:
        return False

    def process(
        self,
        image: PIL.Image.Image,
        page_num: int = 1,
        mode: str = "auto",
        output_format: str = "plain",
        languages: str = "eng",
    ) -> PageResult:
        if mode == "image_description":
            return self._describe(image, page_num)
        prompt = OCR_MARKDOWN_PROMPT if output_format == "markdown" else OCR_PROMPT
        return self._extract(image, page_num, prompt)

    def _extract(self, image: PIL.Image.Image, page_num: int, prompt: str) -> PageResult:
        try:
            b64 = _image_to_base64(image)
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }],
                max_tokens=4096,
            )
            text = response.choices[0].message.content or ""
            return PageResult(page_num=page_num, text=text.strip(), confidence=None)
        except Exception as exc:
            logger.error("OpenAI vision failed on page %d: %s", page_num, exc)
            return PageResult(page_num=page_num, text="", confidence=None)

    def _describe(self, image: PIL.Image.Image, page_num: int) -> PageResult:
        try:
            b64 = _image_to_base64(image)
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": IMAGE_DESCRIPTION_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }],
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            text = _format_description(data)
            return PageResult(page_num=page_num, text=text, confidence=None)
        except Exception as exc:
            logger.error("OpenAI description failed on page %d: %s", page_num, exc)
            return PageResult(page_num=page_num, text="", confidence=None)


def _format_description(data: dict) -> str:
    parts = []
    if title := data.get("title"):
        parts.append(f"## {title}\n")
    if summary := data.get("summary"):
        parts.append(f"{summary}\n")
    if elements := data.get("key_elements"):
        parts.append("**Key elements:**")
        for el in elements:
            parts.append(f"- {el}")
        parts.append("")
    if text := data.get("detected_text"):
        parts.append(f"**Detected text:**\n{text}")
    return "\n".join(parts)
