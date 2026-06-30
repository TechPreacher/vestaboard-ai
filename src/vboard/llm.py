import httpx

from vboard import device, logging_setup
from vboard.config import LLMConfig
from vboard.device import DeviceSpec


def system_prompt(dev: DeviceSpec) -> str:
    return (
        "You write messages for a Vestaboard split-flap display. "
        f"Output ONLY the message text. It must fit on {dev.lines} lines of at "
        f"most {dev.cols} characters each ({dev.content_limit} characters of "
        "content total). Use only A-Z, 0-9, spaces, and basic punctuation "
        ". , ! ? : ; ' \" - + & % = ( ) / @ # $. You may add color accents using "
        "tokens like {red} or {blue} at the start of a line. Keep it punchy. "
        "No explanations, no quotes around the message."
    )


SHORTER_SUFFIX = " Your previous attempt was too long. Make it noticeably shorter."


class LLMError(Exception):
    pass


def _status_hint(status: int) -> str:
    if status in (401, 403):
        return "check the API key."
    if status == 404:
        return "check the base URL and model name."
    if status == 429:
        return "rate limited; try again shortly."
    if status // 100 == 5:
        return "the endpoint reported a server error."
    return ""


def _provider_error(resp: httpx.Response) -> str:
    """Extract the endpoint's own error message (OpenAI shape), if any."""
    try:
        return resp.json().get("error", {}).get("message") or ""
    except (ValueError, AttributeError):
        return ""


def check_connection(
    cfg: LLMConfig,
    *,
    client: httpx.Client | None = None,
) -> tuple[bool, str]:
    """Liveness-check the configured endpoint with a tiny chat completion.

    Sends only model + messages (no tuning params) so quirky models — e.g.
    OpenAI reasoning models that reject a non-default temperature — don't fail a
    connectivity check. Never raises and never includes the API key in its
    return message. Returns (ok, human-readable detail).
    """
    if not cfg.base_url:
        return False, "No base URL configured."
    if not cfg.model:
        return False, "No model configured."
    if cfg.api_key:
        logging_setup.register_secret(cfg.api_key)

    payload = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": "ping"}],
    }
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    owns = client is None
    timeout = httpx.Timeout(cfg.timeout_seconds, connect=10.0)
    client = client or httpx.Client(timeout=timeout)
    try:
        resp = client.post(url, json=payload, headers=headers)
        if resp.status_code // 100 != 2:
            # Surface the endpoint's own error text when it's safe to. For
            # auth failures prefer the canned hint, since some providers echo a
            # (masked) key fragment in their message.
            if resp.status_code in (401, 403):
                detail = _status_hint(resp.status_code)
            else:
                detail = _provider_error(resp) or _status_hint(resp.status_code)
            return False, f"HTTP {resp.status_code}{(' — ' + detail) if detail else ''}"
        try:
            resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            return True, (
                f"Reachable (HTTP {resp.status_code}), but the response "
                "shape was unexpected for an OpenAI-compatible endpoint."
            )
        return True, f"Success — model {cfg.model!r} responded."
    except httpx.HTTPError as e:
        return False, f"Connection failed: {e}"
    finally:
        if owns:
            client.close()


def generate(
    cfg: LLMConfig,
    user_prompt: str,
    *,
    shorter: bool = False,
    dev: DeviceSpec | None = None,
    client: httpx.Client | None = None,
) -> str:
    if cfg.api_key:
        logging_setup.register_secret(cfg.api_key)
    dev = dev or device.get(None)
    system = system_prompt(dev) + (SHORTER_SUFFIX if shorter else "")
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.9,
    }
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    owns = client is None
    # Connect should be quick; reads can be slow on some endpoints/models, so
    # give the read leg the full configured budget.
    timeout = httpx.Timeout(cfg.timeout_seconds, connect=10.0)
    client = client or httpx.Client(timeout=timeout)
    try:
        resp = client.post(url, json=payload, headers=headers)
        if resp.status_code == 400 and "temperature" in resp.text.lower():
            # Some models (e.g. OpenAI's reasoning models) only allow the default
            # temperature and 400 on any other value. Retry once without it
            # rather than failing the whole run.
            payload.pop("temperature", None)
            resp = client.post(url, json=payload, headers=headers)
        if resp.status_code // 100 != 2:
            raise LLMError(f"LLM HTTP {resp.status_code}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"malformed LLM response: {e}") from e
    except httpx.HTTPError as e:
        raise LLMError(f"LLM request failed: {e}") from e
    finally:
        if owns:
            client.close()
