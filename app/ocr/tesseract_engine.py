import logging
import PIL.Image
import pytesseract
from pytesseract import Output
from .base import OCREngine, PageResult, WordBox

logger = logging.getLogger(__name__)


class TesseractEngine(OCREngine):
    @property
    def name(self) -> str:
        return "TesseractEngine"

    def process(
        self,
        image: PIL.Image.Image,
        page_num: int = 1,
        mode: str = "auto",
        output_format: str = "plain",
        languages: str = "eng",
    ) -> PageResult:
        lang = languages.replace(",", "+")
        try:
            data = pytesseract.image_to_data(image, lang=lang, output_type=Output.DICT)
            confs = [c for c in data["conf"] if c != -1]
            confidence = float(sum(confs) / len(confs)) if confs else 0.0

            img_w, img_h = image.size
            boxes: list[WordBox] = []
            for left, top, width, height, conf, text in zip(
                data["left"], data["top"], data["width"], data["height"],
                data["conf"], data["text"],
            ):
                if conf == -1 or not str(text).strip():
                    continue
                boxes.append(WordBox(
                    text=str(text).strip(),
                    confidence=float(conf),
                    x=left / img_w,
                    y=top / img_h,
                    w=width / img_w,
                    h=height / img_h,
                ))

            text = pytesseract.image_to_string(image, lang=lang).strip()
            return PageResult(page_num=page_num, text=text, confidence=confidence, bounding_boxes=boxes)
        except Exception as exc:
            logger.warning("Tesseract failed on page %d: %s", page_num, exc)
            return PageResult(page_num=page_num, text="", confidence=0.0)

    def get_confidence(self, image: PIL.Image.Image, languages: str = "eng") -> float:
        lang = languages.replace(",", "+")
        try:
            data = pytesseract.image_to_data(image, lang=lang, output_type=Output.DICT)
            confs = [c for c in data["conf"] if c != -1]
            return float(sum(confs) / len(confs)) if confs else 0.0
        except Exception:
            return 0.0
