import random
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from faker import Faker
from PIL import Image

from app.pipeline.ingest import UnsupportedFileError, detect_type, ingest
from app.pipeline.ocr import has_text_layer, ocr_text, words_from_tesseract, words_from_text_layer
from app.pipeline.preprocess import BLUR_THRESHOLD, preprocess
from data.generator.generate import write_invoice
from data.generator.model import make_invoice

TODAY = date(2026, 10, 26)
needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract missing")


@pytest.fixture
def invoice_files(tmp_path: Path) -> dict[str, Path]:
    rng = random.Random(4)
    faker = Faker("en_IN")
    faker.seed_instance(4)
    inv = make_invoice(rng, faker, TODAY)
    pdf = write_invoice(inv, tmp_path, "clean", "classic", False, rng)
    jpg = write_invoice(inv, tmp_path, "scan", "classic", True, rng)
    return {"pdf": pdf.file, "jpg": jpg.file, "invoice": inv}  # type: ignore[dict-item]


def test_detect_type_uses_magic_bytes() -> None:
    assert detect_type(b"%PDF-1.7 ...") == "pdf"
    assert detect_type(b"\x89PNG\r\n\x1a\n...") == "png"
    assert detect_type(b"\xff\xd8\xff\xe0...") == "jpeg"
    with pytest.raises(UnsupportedFileError):
        detect_type(b"PK\x03\x04 zip file renamed to .pdf")


def test_broken_pdf_raises() -> None:
    with pytest.raises(UnsupportedFileError, match="Cannot read PDF"):
        ingest(b"%PDF-1.7\nthis is not really a pdf")


def test_pdf_text_layer_in_200_dpi_pixels(invoice_files: dict) -> None:
    mime, pages = ingest(invoice_files["pdf"].read_bytes())
    assert mime == "application/pdf" and len(pages) == 1
    page = pages[0]
    assert page.image.size == (1654, 2339), "A4 at 200 DPI"
    assert has_text_layer(page.text_layer)
    words = words_from_text_layer(page.text_layer, 1)
    number = invoice_files["invoice"].invoice_number
    hit = next(w for w in words if w.text == number)
    assert 0 < hit.x0 < hit.x1 <= 1654 and 0 < hit.y0 < hit.y1 <= 2339
    assert number in ocr_text(words)


def test_image_has_no_text_layer(invoice_files: dict) -> None:
    mime, pages = ingest(invoice_files["jpg"].read_bytes())
    assert mime == "image/jpeg" and pages[0].text_layer == []


def test_blur_score_separates_sharp_from_blurry() -> None:
    rng = np.random.default_rng(0)
    sharp = Image.fromarray((rng.random((400, 400, 3)) > 0.5).astype(np.uint8) * 255)
    flat = Image.new("RGB", (400, 400), "white")
    assert preprocess(sharp).blur_score > BLUR_THRESHOLD > preprocess(flat).blur_score


def test_deskew_detects_rotation(invoice_files: dict) -> None:
    _, pages = ingest(invoice_files["pdf"].read_bytes())
    tilted = pages[0].image.rotate(2.5, expand=True, fillcolor="white")
    result = preprocess(tilted)
    assert abs(result.angle - 2.5) < 0.7


@needs_tesseract
def test_tesseract_reads_scanned_invoice(invoice_files: dict) -> None:
    _, pages = ingest(invoice_files["jpg"].read_bytes())
    pre = preprocess(pages[0].image)
    words = words_from_tesseract(pre.gray, 1)
    text = ocr_text(words).lower()
    assert len(words) > 40
    assert "invoice" in text
    assert invoice_files["invoice"].vendor["name"].split()[0].lower() in text
