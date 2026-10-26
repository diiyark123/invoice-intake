import pytest
from google.genai import errors as genai_errors

from app.pipeline.llm import gemini_provider
from app.pipeline.llm.base import LLMError
from app.pipeline.llm.gemini_provider import GeminiProvider, retry_delay


def test_retry_delay_uses_suggested_wait() -> None:
    assert retry_delay("Please retry in 51.14s.", 1) == pytest.approx(52.14)
    assert retry_delay("no hint", 1) == 5.0 and retry_delay("no hint", 2) == 10.0
    assert retry_delay("retry in 500s", 1) == gemini_provider.MAX_WAIT_SECONDS


class _Resp:
    text = '{"total": "1.00"}'
    usage_metadata = None
    candidates = []


def _provider(outcomes: list) -> tuple[GeminiProvider, list[float]]:
    p = GeminiProvider("fake-key", "gemini-3.5-flash-lite", 100)
    waits: list[float] = []
    p.sleep = waits.append  # type: ignore[method-assign]

    def generate_content(**_):
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    p.client.models.generate_content = generate_content  # type: ignore[method-assign]
    return p, waits


def _api_error(code: int, msg: str = "boom") -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"code": code, "message": msg}})


def test_rate_limit_is_retried_then_succeeds() -> None:
    p, waits = _provider([_api_error(429, "Please retry in 3s."), _Resp()])
    assert p.extract([], "", "prompt").text == '{"total": "1.00"}'
    assert waits == [4.0]


def test_gives_up_after_three_attempts() -> None:
    p, waits = _provider([_api_error(503)] * 3)
    with pytest.raises(LLMError, match="503"):
        p.extract([], "", "prompt")
    assert len(waits) == 2


def test_client_errors_are_not_retried() -> None:
    p, waits = _provider([_api_error(400, "bad request")])
    with pytest.raises(LLMError, match="400"):
        p.extract([], "", "prompt")
    assert waits == []
