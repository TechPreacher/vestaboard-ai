from dataclasses import dataclass, field

from vboard import delivery, device, llm, logging_setup, vbml
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
    # The device's content region actually sent to the board (codes), empty if
    # nothing was delivered. Lets callers record/render it without recompiling.
    grid: list[list[int]] = field(default_factory=list)
    # Which device the message was generated for ("vestaboard" | "note").
    device: str = ""


def run_once(
    cfg: AppConfig,
    prompt: PromptEntry,
    *,
    generate=llm.generate,
    deliver_factory=delivery.make_delivery,
) -> PipelineResult:
    dev = device.get(cfg.vestaboard.device)
    text = ""
    result = None
    attempts = 0
    llm_error: llm.LLMError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        try:
            text = generate(cfg.llm, prompt.text, shorter=(attempt > 1), dev=dev)
        except llm.LLMError as e:
            # Don't abandon the whole run on a single failed/slow attempt: a
            # timeout on a later attempt shouldn't discard usable text from an
            # earlier one. Remember the error and fall through to the fallback.
            llm_error = e
            break
        result = vbml.compile(text, prompt.color_hints_enabled, dev)
        if result.valid:
            break

    truncated = False
    if result is None or not result.valid:
        if not text:
            # Never got any text out of the LLM — nothing to fall back to.
            return PipelineResult(False, text, False, attempts,
                                  f"llm error: {llm_error}", device=dev.key)
        text = vbml.truncate_to_fit(text, dev)
        result = vbml.compile(text, prompt.color_hints_enabled, dev)
        truncated = True
        if not result.valid:
            return PipelineResult(False, text, truncated, attempts,
                                  f"could not produce valid message: {result.reason}",
                                  device=dev.key)

    try:
        board = deliver_factory(cfg.vestaboard)
        board.send(result.grid)
    except delivery.DeliveryError as e:
        return PipelineResult(False, text, truncated, attempts, f"delivery error: {e}",
                              device=dev.key)
    except NotImplementedError as e:
        return PipelineResult(False, text, truncated, attempts, str(e), device=dev.key)

    log.info("delivered prompt id=%s device=%s attempts=%d truncated=%s",
             prompt.id, dev.key, attempts, truncated)
    return PipelineResult(True, text, truncated, attempts, "",
                          vbml.content_region(result.grid, dev), dev.key)
