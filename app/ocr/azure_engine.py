import logging
import PIL.Image
from openai import AzureOpenAI
from .openai_engine import (
    OpenAIVisionEngine, _image_to_base64, _format_description,
    OCR_PROMPT, OCR_MARKDOWN_PROMPT, IMAGE_DESCRIPTION_PROMPT,
)
from .base import PageResult
import base64, io, json

logger = logging.getLogger(__name__)


class AzureVisionEngine(OpenAIVisionEngine):
    def __init__(self, endpoint: str, api_key: str, deployment: str = "gpt-4o"):
        self._client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version="2024-02-01",
        )
        self._model = deployment

    @property
    def name(self) -> str:
        return f"AzureVisionEngine({self._model})"
