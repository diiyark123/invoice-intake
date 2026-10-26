from app.pipeline.grounding import ground_value
from app.pipeline.ocr import Word


def line(page: int, line_id: str, y: float, *texts: str) -> list[Word]:
    words, x = [], 100.0
    for t in texts:
        width = 12.0 * len(t)
        words.append(Word(t, page, x, y, x + width, y + 20, line_id, 95.0))
        x += width + 10
    return words


WORDS = (
    line(1, "1-1", 50, "Apex", "Industrial", "Supplies", "Pvt", "Ltd")
    + line(1, "1-2", 90, "Invoice", "No:", "INV-2026-0042")
    + line(1, "1-3", 130, "Invoice", "Date:", "12/03/2026")
    + line(1, "1-4", 400, "Subtotal", "1,12,146.44")
    + line(1, "1-5", 430, "GST", "@", "5%", "5,607.32")
    + line(2, "2-1", 60, "Total", "(INR)", "1,17,753.76")
)


def test_text_value_found_with_merged_bbox() -> None:
    g = ground_value("Apex Industrial Supplies Pvt Ltd", "text", WORDS)
    assert g.page == 1
    assert g.score == 1.0
    assert g.source_text == "Apex Industrial Supplies Pvt Ltd"
    first, last = WORDS[0], WORDS[4]
    assert g.bbox == {"x0": first.x0, "y0": first.y0, "x1": last.x1, "y1": last.y1}


def test_invoice_number_exact() -> None:
    g = ground_value("INV-2026-0042", "text", WORDS)
    assert g.source_text == "INV-2026-0042" and g.score == 1.0


def test_amount_matches_on_normalized_value() -> None:
    g = ground_value("112146.44", "amount", WORDS)  # printed with Indian grouping
    assert g.source_text == "1,12,146.44" and g.score == 1.0
    assert g.bbox is not None and g.bbox["y0"] == 400


def test_amount_on_second_page() -> None:
    g = ground_value("117,753.76", "amount", WORDS)
    assert g.page == 2 and g.source_text == "1,17,753.76"


def test_iso_date_matches_printed_day_first_date() -> None:
    g = ground_value("2026-03-12", "date", WORDS)
    assert g.source_text == "12/03/2026" and g.score == 1.0


def test_close_text_gets_partial_score() -> None:
    g = ground_value("Apex Industrial Suplies", "text", WORDS)  # OCR-style typo
    assert g.page == 1 and 0.9 < g.score < 1.0


def test_missing_value_has_no_location() -> None:
    for value, kind in [("99,999.99", "amount"), ("Riverstone Furniture", "text"), (None, "text")]:
        g = ground_value(value, kind, WORDS)
        assert g.page is None and g.bbox is None and g.source_text is None and g.score == 0.0


def test_spans_do_not_cross_lines() -> None:
    g = ground_value("Ltd Invoice No:", "text", WORDS)
    assert g.score < 1.0


def test_garbled_date_matches_its_printed_form_not_an_invoice_number() -> None:
    words = line(1, "1-1", 50, "Invoice", "No:", "INV-2026-0527") + line(
        1, "1-2", 90, "Date:", "27/O5/2026"  # OCR read 0 as O
    )
    g = ground_value("2026-05-27", "date", words)
    assert g.source_text == "27/O5/2026" and 0.85 <= g.score < 1.0


def test_currency_with_ocr_comma() -> None:
    words = line(1, "1-1", 50, "Grand", "Total", "Rs,", "68,159.66")
    g = ground_value("INR", "currency", words)
    assert g.source_text == "Rs," and g.score == 1.0
