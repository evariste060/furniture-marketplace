"""Image validation and the public source (module 7; ADR-009: no format conversion, no resized
variants, the exact original kept)."""

import io
import threading
import time

import pytest
from PIL import Image

from app.services import image_processing
from app.services.image_processing import (
    JPEG_QUALITY,
    MAX_IMAGE_PIXELS,
    MAX_LONGEST_SIDE,
    MAX_UPLOAD_BYTES,
    InvalidImage,
    process_image,
    process_image_limited,
)

EXIF_ORIENTATION, EXIF_MAKE, EXIF_GPS_IFD = 0x0112, 0x010F, 0x8825


def encode(image: Image.Image, image_format: str, **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, image_format, **options)
    return buffer.getvalue()


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


# ---- formats and the original ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("image_format", "extension", "content_type"),
    [("JPEG", "jpg", "image/jpeg"), ("PNG", "png", "image/png"), ("WEBP", "webp", "image/webp")],
)
def test_each_format_keeps_its_format_and_the_original_is_kept_byte_for_byte(
    image_format, extension, content_type
):
    raw = encode(Image.new("RGB", (640, 480), "blue"), image_format)
    result = process_image(raw)
    assert result.original == raw  # exact upload, unchanged
    assert opened(result.public).format == image_format  # no format conversion
    assert (result.extension, result.content_type) == (extension, content_type)


def test_pillow_limit_is_set_explicitly():
    assert MAX_IMAGE_PIXELS == 50_000_000
    assert Image.MAX_IMAGE_PIXELS == MAX_IMAGE_PIXELS


# ---- size: no variants, only the 2400 px cap -------------------------------------------------
def test_images_up_to_2400_px_keep_their_size():
    result = process_image(encode(Image.new("RGB", (2400, 1600), "green"), "PNG"))
    assert opened(result.public).size == (2400, 1600)
    assert (result.width, result.height) == (2400, 1600)


@pytest.mark.parametrize(
    ("size", "expected"),
    [((4800, 2400), (2400, 1200)), ((2000, 6000), (800, 2400))],
    ids=["wide", "tall"],
)
def test_only_the_longest_side_is_capped_and_the_aspect_ratio_is_kept(size, expected):
    result = process_image(encode(Image.new("RGB", size, "white"), "JPEG"))
    assert max(expected) == MAX_LONGEST_SIDE
    assert opened(result.public).size == expected == (result.width, result.height)


def test_small_images_are_never_enlarged():
    result = process_image(encode(Image.new("RGB", (300, 200), "green"), "WEBP"))
    assert opened(result.public).size == (300, 200)


def test_there_are_no_resized_variants_or_thumbnails():
    result = process_image(encode(Image.new("RGB", (3200, 1600), "blue"), "JPEG"))
    assert not hasattr(result, "thumbnail") and not hasattr(result, "data")


def test_jpeg_public_source_is_high_quality():
    # Noise compresses badly, so the size difference between qualities is clear.
    noisy = Image.effect_noise((256, 256), 64).convert("RGB")
    at_85 = len(encode(noisy, "JPEG", quality=85))
    public = process_image(encode(noisy, "JPEG", quality=100)).public
    assert JPEG_QUALITY == 92 and len(public) > at_85


# ---- orientation, metadata, transparency, frames ---------------------------------------------
def test_exif_orientation_is_applied_and_all_metadata_is_stripped():
    source = Image.new("RGB", (200, 100), "red")
    exif = source.getexif()
    exif[EXIF_ORIENTATION] = 6  # stored sideways: "rotate 90 degrees clockwise to view"
    exif[EXIF_MAKE] = "TestCamera"
    exif.get_ifd(EXIF_GPS_IFD)[2] = (1.0, 2.0, 3.0)  # GPS latitude
    raw = encode(source, "JPEG", exif=exif.tobytes(), icc_profile=b"not-a-real-profile")
    assert opened(raw).getexif().get(EXIF_MAKE) == "TestCamera"  # the source really has it

    result = process_image(raw)
    out = opened(result.public)
    assert out.size == (100, 200)  # upright: width and height swapped
    assert dict(out.getexif()) == {}
    assert "exif" not in out.info and "icc_profile" not in out.info
    assert (result.width, result.height) == (100, 200)
    # The private original keeps everything, untouched.
    assert result.original == raw and opened(result.original).getexif().get(EXIF_MAKE)


def test_png_text_metadata_is_stripped():
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Comment", "secret location")
    raw = encode(Image.new("RGB", (20, 20)), "PNG", pnginfo=info)
    assert opened(raw).info.get("Comment") == "secret location"
    assert "Comment" not in opened(process_image(raw).public).info


@pytest.mark.parametrize("image_format", ["PNG", "WEBP"])
def test_transparency_is_kept_for_png_and_webp(image_format):
    source = Image.new("RGBA", (40, 40), (255, 0, 0, 0))
    source.putpixel((5, 5), (0, 0, 255, 255))
    out = opened(process_image(encode(source, image_format, lossless=True)).public)
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0 and out.getpixel((5, 5))[3] == 255


def test_palette_png_with_transparency_keeps_it():
    source = Image.new("P", (20, 20), 0)
    source.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
    source.putpixel((1, 1), 1)
    out = opened(process_image(encode(source, "PNG", transparency=0)).public)
    assert out.mode == "RGBA" and out.getpixel((0, 0))[3] == 0 and out.getpixel((1, 1))[3] == 255


def test_jpeg_output_has_no_alpha_channel():
    source = Image.new("RGB", (50, 50), "yellow")
    assert opened(process_image(encode(source, "JPEG")).public).mode == "RGB"


@pytest.mark.parametrize("image_format", ["PNG", "WEBP"])
def test_animated_images_keep_only_the_first_frame(image_format):
    frames = [Image.new("RGB", (60, 60), colour) for colour in ("red", "lime", "blue")]
    raw = encode(frames[0], image_format, save_all=True, append_images=frames[1:], duration=100)
    assert getattr(opened(raw), "n_frames", 1) == 3
    out = opened(process_image(raw).public)
    assert getattr(out, "n_frames", 1) == 1
    red, _, blue = out.convert("RGB").getpixel((30, 30))
    assert red > 200 and blue < 50  # frame 1 (red)


# ---- rejection ---------------------------------------------------------------------------------
def test_the_format_is_detected_from_the_content_not_a_name():
    # The service receives only bytes; a PNG is a PNG whatever it was called by the client.
    result = process_image(encode(Image.new("RGB", (10, 10)), "PNG"))
    assert (result.extension, result.content_type) == ("png", "image/png")


@pytest.mark.parametrize("image_format", ["GIF", "BMP", "TIFF", "ICO"])
def test_unsupported_image_formats_are_rejected(image_format):
    with pytest.raises(InvalidImage, match="Only JPEG, PNG and WebP"):
        process_image(encode(Image.new("RGB", (16, 16)), image_format))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not an image at all",
        b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n",
        b"\xff\xd8\xff\xe0" + b"\x00" * 40,  # JPEG signature, no image data
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
    ],
    ids=["empty", "text", "pdf", "fake-jpeg-header", "svg"],
)
def test_non_images_are_rejected(raw):
    with pytest.raises(InvalidImage):
        process_image(raw)


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_corrupt_truncated_images_are_rejected(image_format):
    raw = encode(Image.effect_noise((400, 400), 64).convert("RGB"), image_format)
    with pytest.raises(InvalidImage, match="not a valid"):
        process_image(raw[: len(raw) // 2])


def test_files_over_5_mb_are_rejected():
    with pytest.raises(InvalidImage, match="larger than 5 MB"):
        process_image(b"\x00" * (MAX_UPLOAD_BYTES + 1))


def test_images_with_too_many_pixels_are_rejected_before_decoding(monkeypatch):
    monkeypatch.setattr(image_processing, "MAX_IMAGE_PIXELS", 99)
    with pytest.raises(InvalidImage, match="dimensions"):
        process_image(encode(Image.new("RGB", (10, 10)), "PNG"))


def test_a_real_decompression_bomb_is_rejected():
    # A tiny file declaring 20 000 x 20 000 pixels (400 MP, eight times the limit): a PNG of one
    # colour compresses to a few hundred kilobytes, but decoding it would need over a gigabyte.
    bomb = encode(Image.new("1", (20_000, 20_000)), "PNG", optimize=True)
    assert len(bomb) < MAX_UPLOAD_BYTES
    with pytest.raises(InvalidImage):
        process_image(bomb)


@pytest.mark.parametrize("pixels", [150, 500], ids=["bomb-warning", "bomb-error"])
def test_pillow_decompression_bomb_checks_are_errors(monkeypatch, pixels):
    # Above Image.MAX_IMAGE_PIXELS Pillow warns; above twice that it raises. Both are rejected.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    side = int(pixels**0.5) + 1
    with pytest.raises(InvalidImage):
        process_image(encode(Image.new("RGB", (side, side)), "PNG"))


# ---- concurrency limit -------------------------------------------------------------------------
def test_processing_runs_at_most_the_configured_number_at_once(monkeypatch):
    image_processing._slots.cache_clear()
    monkeypatch.setattr(
        image_processing, "get_settings", lambda: type("S", (), {"image_processing_concurrency": 2})
    )
    running = 0
    peak = 0
    lock = threading.Lock()

    def slow(raw: bytes):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1

    monkeypatch.setattr(image_processing, "process_image", slow)
    threads = [threading.Thread(target=process_image_limited, args=(b"",)) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    image_processing._slots.cache_clear()
    assert peak == 2
