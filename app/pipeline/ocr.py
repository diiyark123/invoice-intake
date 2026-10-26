"""Words with bounding boxes: from the PDF text layer when present (D5), else Tesseract."""

from dataclasses import dataclass

import numpy as np
import pytesseract

from app.pipeline.ingest import PdfWord

MIN_TEXT_LAYER_WORDS = 20  # D5


@dataclass(frozen=True)
class Word:
    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    line_id: str
    conf: float  # 0-100; 100 for text-layer words


def has_text_layer(words: list[PdfWord]) -> bool:
    return len(words) >= MIN_TEXT_LAYER_WORDS


def words_from_text_layer(words: list[PdfWord], page: int) -> list[Word]:
    return [Word(w.text, page, w.x0, w.y0, w.x1, w.y1, w.line_id, 100.0) for w in words]


def words_from_tesseract(
    gray: np.ndarray, page: int, tesseract_cmd: str | None = None
) -> list[Word]:
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT, config="--psm 3")
    words = []
    for i, text in enumerate(data["text"]):
        conf = float(data["conf"][i])
        if not text.strip() or conf < 0:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        line_id = f"{data['block_num'][i]}-{data['par_num'][i]}-{data['line_num'][i]}"
        words.append(Word(text.strip(), page, x, y, x + w, y + h, line_id, conf))
    return words


def ocr_text(words: list[Word]) -> str:
    """Plain text for the LLM: one line per OCR line, pages separated by a marker."""
    lines: list[str] = []
    current: tuple[int, str] | None = None
    page_seen: int | None = None
    for w in words:
        if w.page != page_seen:
            lines.append(f"--- page {w.page} ---")
            page_seen = w.page
        key = (w.page, w.line_id)
        if key != current:
            lines.append(w.text)
            current = key
        else:
            lines[-1] += " " + w.text
    return "\n".join(lines)
