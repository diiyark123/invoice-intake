"""File type detection (magic bytes) and page rendering at 200 DPI (D4)."""

import io
from dataclasses import dataclass

import pymupdf
from PIL import Image, ImageOps

RENDER_DPI = 200
PDF_POINT_TO_PIXEL = RENDER_DPI / 72  # D4: text-layer coordinates are in points

MIME_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg"}


class UnsupportedFileError(ValueError):
    pass


@dataclass
class PdfWord:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    line_id: str


@dataclass
class Page:
    number: int  # 1-based
    image: Image.Image  # RGB, 200 DPI
    text_layer: list[PdfWord]  # empty for images or scanned PDFs


def detect_type(data: bytes) -> str:
    """Return 'pdf', 'png' or 'jpeg' from the first bytes; never trust the file extension."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    raise UnsupportedFileError("Unsupported file type (only PDF, PNG and JPEG are accepted)")


def _pdf_pages(data: bytes) -> list[Page]:
    pages = []
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise UnsupportedFileError(f"Cannot read PDF: {exc}") from exc
    with doc:
        if doc.page_count == 0:
            raise UnsupportedFileError("PDF has no pages")
        for index, page in enumerate(doc):
            pix = page.get_pixmap(dpi=RENDER_DPI)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            words = [
                PdfWord(
                    text=w[4],
                    x0=w[0] * PDF_POINT_TO_PIXEL,
                    y0=w[1] * PDF_POINT_TO_PIXEL,
                    x1=w[2] * PDF_POINT_TO_PIXEL,
                    y1=w[3] * PDF_POINT_TO_PIXEL,
                    line_id=f"{w[5]}-{w[6]}",
                )
                for w in page.get_text("words")
                if w[4].strip()
            ]
            pages.append(Page(number=index + 1, image=image, text_layer=words))
    return pages


def _image_page(data: bytes) -> list[Page]:
    with Image.open(io.BytesIO(data)) as img:
        image = ImageOps.exif_transpose(img).convert("RGB")
    return [Page(number=1, image=image, text_layer=[])]


def ingest(data: bytes) -> tuple[str, list[Page]]:
    """Detect the type and return (mime_type, pages)."""
    kind = detect_type(data)
    pages = _pdf_pages(data) if kind == "pdf" else _image_page(data)
    return MIME_TYPES[kind], pages
