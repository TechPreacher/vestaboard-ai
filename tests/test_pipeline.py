from vboard import pipeline
from vboard.config import AppConfig, PromptEntry, VestaboardConfig

PROMPT = PromptEntry(id="1", text="weather", cron="* * * * *")
CFG = AppConfig(vestaboard=VestaboardConfig(backend="cloud", cloud_key="k"))


class FakeBoard:
    def __init__(self):
        self.sent = None

    def send(self, grid):
        self.sent = grid


def test_first_attempt_valid_delivers():
    board = FakeBoard()
    r = pipeline.run_once(
        CFG, PROMPT,
        generate=lambda cfg, p, shorter=False: "RAIN TODAY",
        deliver_factory=lambda vcfg, client=None: board,
    )
    assert r.delivered is True
    assert r.attempts == 1
    assert r.truncated is False
    assert board.sent is not None


def test_regenerates_when_first_too_long():
    calls = []

    def gen(cfg, p, shorter=False):
        calls.append(shorter)
        return "X" * 60 if not shorter else "SHORT"

    board = FakeBoard()
    r = pipeline.run_once(CFG, PROMPT, generate=gen, deliver_factory=lambda v, client=None: board)
    assert r.delivered is True
    assert r.attempts == 2
    assert calls == [False, True]


def test_truncates_when_all_attempts_too_long():
    board = FakeBoard()
    r = pipeline.run_once(
        CFG, PROMPT,
        generate=lambda cfg, p, shorter=False: " ".join(["WORD"] * 30),
        deliver_factory=lambda v, client=None: board,
    )
    assert r.delivered is True
    assert r.truncated is True
    assert board.sent is not None


def test_delivery_error_reported_not_raised():
    from vboard.delivery import DeliveryError

    class BadBoard:
        def send(self, grid):
            raise DeliveryError("down")

    r = pipeline.run_once(
        CFG, PROMPT,
        generate=lambda cfg, p, shorter=False: "OK",
        deliver_factory=lambda v, client=None: BadBoard(),
    )
    assert r.delivered is False
    assert "down" in r.error


def test_llm_error_reported_not_raised():
    from vboard.llm import LLMError

    def gen(cfg, p, shorter=False):
        raise LLMError("no key")

    board = FakeBoard()
    r = pipeline.run_once(CFG, PROMPT, generate=gen, deliver_factory=lambda v, client=None: board)
    assert r.delivered is False
    assert "no key" in r.error


def test_local_backend_not_implemented_reported():
    cfg = AppConfig(
        vestaboard=VestaboardConfig(
            backend="local", local_endpoint="http://x", local_key="k"
        )
    )
    prompt = PromptEntry(id="1", text="weather", cron="* * * * *")
    r = pipeline.run_once(cfg, prompt, generate=lambda c, p, shorter=False: "RAIN TODAY")
    # uses the real make_delivery -> LocalAPI -> NotImplementedError
    assert r.delivered is False
    assert "local" in r.error.lower()
