import httpx

from vboard import logging_setup
from vboard.config import LLMConfig

log = logging_setup.get_logger("vboard.llm")

SYSTEM_PROMPT = (
    "You write messages for a Vestaboard split-flap display. "
    "Output ONLY the message text. It must fit on 3 lines of at most 15 "
    "characters each (45 characters of content total). Use only A-Z, 0-9, "
    "spaces, and basic punctuation . , ! ? : ; ' \" - + & % = ( ) / @ # $. "
    "You may add color accents using tokens like {red} or {blue} at the start "
    "of a line. Keep it punchy. No explanations, no quotes around the message."
)

SHORTER_SUFFIX = " Your previous attempt was too long. Make it noticeably shorter."


class LLMError(Exception):
    pass


def generate(
    cfg: LLMConfig,
    user_prompt: str,
    *,
    shorter: bool = False,
    client: httpx.Client | None = None,
) -> str:
    if cfg.api_key:
        logging_setup.register_secret(cfg.api_key)
    system = SYSTEM_PROMPT + (SHORTER_SUFFIX if shorter else "")
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
    client = client or httpx.Client(timeout=30.0)
    try:
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
