import logging
import PIL.Image
import PIL.ImageOps

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    def process(self, image: PIL.Image.Image) -> PIL.Image.Image:
        image = PIL.ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        return image

    def process_all(self, images: list[PIL.Image.Image]) -> list[PIL.Image.Image]:
        return [self.process(img) for img in images]
