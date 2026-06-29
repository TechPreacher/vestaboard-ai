import httpx
import pytest
import respx

from vboard import device, llm
from vboard.config import LLMConfig

CFG = LLMConfig(base_url="https://api.example/v1", model="m", api_key="secret")


def test_system_prompt_reflects_device_dimensions():
    note = llm.system_prompt(device.DEVICES["note"])
    board = llm.system_prompt(device.DEVICES["vestaboard"])
    assert "3 lines" in note and "15 characters" in note and "45 characters" in note
    assert "6 lines" in board and "22 characters" in board and "132 characters" in board


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


@respx.mock
def test_check_connection_success():
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "pong"}}]
        })
    )
    ok, detail = llm.check_connection(CFG)
    assert ok is True
    assert "m" in detail


@respx.mock
def test_check_connection_bad_key_reports_auth_hint():
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(401, text="unauthorized")
    )
    ok, detail = llm.check_connection(CFG)
    assert ok is False
    assert "401" in detail and "key" in detail.lower()


@respx.mock
def test_check_connection_connection_error_is_caught():
    respx.post("https://api.example/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("no route")
    )
    ok, detail = llm.check_connection(CFG)
    assert ok is False
    assert "failed" in detail.lower()


def test_check_connection_missing_config_is_reported():
    ok, detail = llm.check_connection(LLMConfig())
    assert ok is False
    assert "base url" in detail.lower()


@respx.mock
def test_check_connection_surfaces_provider_error_message():
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(400, json={
            "error": {"message": "Unsupported value: 'temperature' does not support 0"}
        })
    )
    ok, detail = llm.check_connection(CFG)
    assert ok is False
    assert "400" in detail
    assert "temperature" in detail.lower()


@respx.mock
def test_generate_retries_without_temperature_on_400():
    route = respx.post("https://api.example/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(400, json={
                "error": {"message": "temperature does not support 0.9"}
            }),
            httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]}),
        ]
    )
    out = llm.generate(CFG, "weather")
    assert out == "OK"
    assert route.call_count == 2
    # The retry must drop the temperature parameter.
    assert "temperature" in route.calls[0].request.content.decode()
    assert "temperature" not in route.calls[1].request.content.decode()


@respx.mock
def test_generate_does_not_retry_on_unrelated_400():
    route = respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": {"message": "bad request"}})
    )
    with pytest.raises(llm.LLMError):
        llm.generate(CFG, "weather")
    assert route.call_count == 1  # no retry when the 400 isn't about temperature


@respx.mock
def test_check_connection_does_not_leak_key():
    respx.post("https://api.example/v1/chat/completions").mock(
        return_value=httpx.Response(401, text="nope")
    )
    ok, detail = llm.check_connection(CFG)
    assert CFG.api_key not in detail
