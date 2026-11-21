"""Validate uploads and build the public source of an image (module 7; ADR-009).

The uploaded bytes are decoded with Pillow; the file name and declared content type are never
trusted. Only JPEG, PNG and WebP are accepted, at most 5 MB and MAX_IMAGE_PIXELS pixels; corrupt
files and decompression bombs are refused before any file is written. There is no format
conversion and no set of resized variants: resizing for display happens at delivery time (the
Next.js image optimizer now, a CDN later). The service stores two files:
- the private original: the uploaded bytes, unchanged;
- the public source, in the original format: the first frame of an animated image, turned upright
  from its EXIF orientation, rebuilt from raw pixels so no metadata (EXIF, GPS, ICC profile,
  comments) survives, transparency kept (PNG, WebP), and scaled down only when its longest side is
  above 2400 px. JPEG and WebP are re-encoded at quality 92; PNG is lossless.

Pillow work is CPU-bound, so it never runs on the event loop: the upload endpoints are sync
(FastAPI runs them in its threadpool), and process_image_limited lets at most
IMAGE_PROCESSING_CONCURRENCY images be processed at once per API process.
"""

import io
import threading
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB (plan §7 Q7)
MAX_LONGEST_SIDE = 2400
# Decompression-bomb guard: refuse images whose pixel count is far beyond any product photo,
# before decoding their pixel data. Set on Pillow too, so its own check uses the same limit (it
# warns above it and raises above twice it); the warning is treated as an error below.
MAX_IMAGE_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
JPEG_QUALITY = 92
WEBP_QUALITY = 92

FORMATS = {  # Pillow format -> (file extension, content type)
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


class InvalidImage(Exception):
    """The bytes are not an acceptable JPEG, PNG or WebP image; the message is safe to show."""


@dataclass(frozen=True)
class ProcessedImage:
    original: bytes  # the upload, byte for byte
    public: bytes  # the sanitised public source
    width: int  # of the public source
    height: int
    extension: str
    content_type: str


def _decode(raw: bytes) -> tuple[Image.Image, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(raw))
            image_format = image.format or ""
            if image_format not in FORMATS:
                raise InvalidImage("Only JPEG, PNG and WebP images are accepted.")
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise InvalidImage("The image dimensions are not allowed.")
            image.seek(0)  # first frame of an animated image
            image.load()  # decode the pixel data now, so a corrupt file fails here
    except InvalidImage:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
        EOFError,
    ):
        raise InvalidImage("The file is not a valid JPEG, PNG or WebP image.") from None
    return image, image_format


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info


def _clean(image: Image.Image, image_format: str) -> Image.Image:
    """Upright pixels in a format-appropriate mode, with no metadata attached."""
    upright = ImageOps.exif_transpose(image)
    if image_format == "JPEG":
        mode = "L" if upright.mode == "L" else "RGB"
    else:
        mode = "RGBA" if _has_alpha(upright) else "RGB"
    converted = upright.convert(mode)
    # Rebuilding from raw pixels drops every metadata block (info, EXIF, ICC profile).
    return Image.frombytes(mode, converted.size, converted.tobytes())


def _fit_longest_side(image: Image.Image, limit: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= limit:
        return image
    scale = limit / longest
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _encode(image: Image.Image, image_format: str) -> bytes:
    buffer = io.BytesIO()
    if image_format == "JPEG":
        image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    elif image_format == "WEBP":
        image.save(buffer, "WEBP", quality=WEBP_QUALITY, method=4)
    else:
        image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def process_image(raw: bytes) -> ProcessedImage:
    """Validate an upload and build its public source. Raises InvalidImage when not acceptable."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidImage("The image is larger than 5 MB.")
    decoded, image_format = _decode(raw)
    with decoded:
        public = _fit_longest_side(_clean(decoded, image_format), MAX_LONGEST_SIDE)
    extension, content_type = FORMATS[image_format]
    return ProcessedImage(
        original=raw,
        public=_encode(public, image_format),
        width=public.width,
        height=public.height,
        extension=extension,
        content_type=content_type,
    )


@lru_cache
def _slots() -> threading.BoundedSemaphore:
    return threading.BoundedSemaphore(get_settings().image_processing_concurrency)


@contextmanager
def processing_slot() -> Iterator[None]:
    """Hold one of the IMAGE_PROCESSING_CONCURRENCY slots; waits while all are taken."""
    slots = _slots()
    with slots:
        yield


def process_image_limited(raw: bytes) -> ProcessedImage:
    """process_image, with at most IMAGE_PROCESSING_CONCURRENCY running at once."""
    with processing_slot():
        return process_image(raw)
