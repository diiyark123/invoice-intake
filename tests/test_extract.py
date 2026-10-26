import pytest

from app.pipeline.extract import (
    PROMPT_VERSION,
    ExtractionError,
    load_prompt,
    parse_llm_json,
    run_extraction,
)
from app.pipeline.llm.base import LLMError
from tests.fakes import FakeLLMProvider

GOOD = {
    "doc_class": "invoice",
    "vendor_name": "Apex Industrial Supplies Pvt Ltd",
    "invoice_number": "INV-0042",
    "invoice_date": "2026-03-12",
    "due_date": None,
    "currency": "INR",
    "subtotal": "100.00",
    "tax": "18.00",
    "total": "118.00",
    "line_items": [
        {"description": "Bolts", "quantity": "2", "unit_price": "50.00", "amount": "100.00"}
    ],
}


def test_parse_plain_and_fenced_json() -> None:
    assert parse_llm_json('{"a": 1}') == {"a": 1}
    assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_llm_json('Here you go:\n{"a": 1}\nThanks') == {"a": 1}


@pytest.mark.parametrize("bad", ["", "no json here", "[1, 2]", '{"a": '])
def test_parse_rejects_bad_output(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_llm_json(bad)


def test_prompt_file_exists_and_is_versioned() -> None:
    for version in ("extract_v1", "extract_v2", PROMPT_VERSION):
        prompt = load_prompt(version)
        assert "null" in prompt and "JSON" in prompt and "doc_class" in prompt
    assert "source of truth" in load_prompt("extract_v2"), "v2 tells the model to trust the image"


def test_success_first_try() -> None:
    fake = FakeLLMProvider(GOOD)
    out = run_extraction(fake, [], "ocr text")
    assert len(fake.calls) == 1
    assert out.invoice.invoice_number == "INV-0042"
    assert out.invoice.line_items[0].amount == "100.00"
    assert out.model == "fake-model" and out.input_tokens == 1000 and out.output_tokens == 200
    assert "ocr text" == fake.calls[0]["ocr_text"]


def test_bad_json_then_good_retries_once() -> None:
    fake = FakeLLMProvider("not json", GOOD)
    out = run_extraction(fake, [], "")
    assert len(fake.calls) == 2
    assert out.input_tokens == 2000, "tokens from both calls are counted"


def test_bad_json_twice_fails() -> None:
    fake = FakeLLMProvider("not json", "still not json")
    with pytest.raises(ExtractionError, match="invalid JSON after 2 attempts"):
        run_extraction(fake, [], "")
    assert len(fake.calls) == 2


def test_numbers_are_kept_as_text_and_unknown_class_becomes_other() -> None:
    fake = FakeLLMProvider({**GOOD, "total": 118.5, "doc_class": "receipt", "line_items": None})
    out = run_extraction(fake, [], "")
    assert out.invoice.total == "118.5"
    assert out.invoice.doc_class == "other"
    assert out.invoice.line_items == []


def test_provider_error_propagates() -> None:
    with pytest.raises(LLMError):
        run_extraction(FakeLLMProvider(LLMError("quota exceeded")), [], "")
