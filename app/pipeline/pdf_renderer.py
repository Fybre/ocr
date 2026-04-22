import logging
from pathlib import Path
import PIL.Image

logger = logging.getLogger(__name__)


class PDFRenderer:
    def render(self, file_path: str | Path, dpi: int = 300) -> list[PIL.Image.Image]:
        import fitz  # PyMuPDF
        images = []
        doc = fitz.open(str(file_path))
        try:
            matrix = fitz.Matrix(dpi / 72, dpi / 72)
            for page_num, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                img = PIL.Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
                logger.debug("Rendered PDF page %d (%dx%d)", page_num, pix.width, pix.height)
        finally:
            doc.close()
        return images
