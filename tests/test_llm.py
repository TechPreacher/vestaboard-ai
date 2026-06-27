import httpx
import pytest
import respx

from vboard import llm
from vboard.config import LLMConfig

CFG = LLMConfig(base_url="https://api.example/v1", model="m", api_key="secret")


@respx.mock
def test_generate_returns_message_content():
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "RAIN TODAY"}}]
        })
    )
    out = llm.generate(CFG, "weather")
    assert out == "RAIN TODAY"


@respx.mock
def test_generate_shorter_adds_instruction_and_still_parses():
    route = respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "RAIN"}}]
        })
    )
    out = llm.generate(CFG, "weather", shorter=True)
    assert out == "RAIN"
    body = route.calls.last.request.content.decode()
    assert "shorter" in body.lower()


@respx.mock
def test_generate_raises_on_error_status():
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(llm.LLMError):
        llm.generate(CFG, "weather")
