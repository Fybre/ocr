from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import PIL.Image


@dataclass
class WordBox:
    text: str
    confidence: float  # 0–100
    x: float  # left edge as fraction of image width (0–1)
    y: float  # top edge as fraction of image height (0–1)
    w: float  # box width as fraction of image width
    h: float  # box height as fraction of image height


@dataclass
class PageResult:
    page_num: int
    text: str
    confidence: float | None = None  # 0–100; None for LLM engines
    bounding_boxes: list[WordBox] = field(default_factory=list)


class OCREngine(ABC):
    @abstractmethod
    def process(
        self,
        image: PIL.Image.Image,
        page_num: int = 1,
        mode: str = "auto",
        output_format: str = "plain",
        languages: str = "eng",
    ) -> PageResult: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def supports_confidence(self) -> bool:
        return True
