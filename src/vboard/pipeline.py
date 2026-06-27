from dataclasses import dataclass

from vboard import delivery, llm, logging_setup, vbml
from vboard.config import AppConfig, PromptEntry

log = logging_setup.get_logger("vboard.pipeline")

MAX_ATTEMPTS = 3


@dataclass
class PipelineResult:
    delivered: bool
    text: str
    truncated: bool
    attempts: int
    error: str


def run_once(
    cfg: AppConfig,
    prompt: PromptEntry,
    *,
    generate=llm.generate,
    deliver_factory=delivery.make_delivery,
) -> PipelineResult:
    text = ""
    result = None
    attempts = 0
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            attempts = attempt
            text = generate(cfg.llm, prompt.text, shorter=(attempt > 1))
            result = vbml.compile(text, prompt.color_hints_enabled)
            if result.valid:
                break
    except llm.LLMError as e:
        return PipelineResult(False, text, False, attempts, f"llm error: {e}")

    truncated = False
    if result is None or not result.valid:
        text = vbml.truncate_to_fit(text)
        result = vbml.compile(text, prompt.color_hints_enabled)
        truncated = True
        if not result.valid:
            return PipelineResult(False, text, truncated, attempts,
                                  f"could not produce valid message: {result.reason}")

    try:
        board = deliver_factory(cfg.vestaboard)
        board.send(result.grid)
    except delivery.DeliveryError as e:
        return PipelineResult(False, text, truncated, attempts, f"delivery error: {e}")
    except NotImplementedError as e:
        return PipelineResult(False, text, truncated, attempts, str(e))

    log.info("delivered prompt id=%s attempts=%d truncated=%s", prompt.id, attempts, truncated)
    return PipelineResult(True, text, truncated, attempts, "")
