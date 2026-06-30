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
        CFG,
        PROMPT,
        generate=lambda cfg, p, shorter=False, dev=None: "RAIN TODAY",
        deliver_factory=lambda vcfg, client=None: board,
    )
    assert r.delivered is True
    assert r.attempts == 1
    assert r.truncated is False
    assert board.sent is not None
    # delivered result carries the 3x15 Note region for history/preview
    assert len(r.grid) == 3
    assert all(len(row) == 15 for row in r.grid)


def test_regenerates_when_first_too_long():
    calls = []

    def gen(cfg, p, shorter=False, dev=None):
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
        CFG,
        PROMPT,
        generate=lambda cfg, p, shorter=False, dev=None: " ".join(["WORD"] * 30),
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
        CFG,
        PROMPT,
        generate=lambda cfg, p, shorter=False, dev=None: "OK",
        deliver_factory=lambda v, client=None: BadBoard(),
    )
    assert r.delivered is False
    assert "down" in r.error


def test_llm_error_reported_not_raised():
    from vboard.llm import LLMError

    def gen(cfg, p, shorter=False, dev=None):
        raise LLMError("no key")

    board = FakeBoard()
    r = pipeline.run_once(CFG, PROMPT, generate=gen, deliver_factory=lambda v, client=None: board)
    assert r.delivered is False
    assert "no key" in r.error


def test_timeout_on_later_attempt_falls_back_to_truncation():
    from vboard.llm import LLMError

    # Attempt 1 returns usable-but-too-long text; attempt 2 (shorter) times out.
    # The timeout must not discard attempt 1's text — we truncate and deliver.
    def gen(cfg, p, shorter=False, dev=None):
        if shorter:
            raise LLMError("read timed out")
        return " ".join(["WORD"] * 30)

    board = FakeBoard()
    r = pipeline.run_once(CFG, PROMPT, generate=gen, deliver_factory=lambda v, client=None: board)
    assert r.delivered is True
    assert r.truncated is True
    assert r.attempts == 2
    assert board.sent is not None


def test_timeout_on_first_attempt_with_no_text_reports_error():
    from vboard.llm import LLMError

    def gen(cfg, p, shorter=False, dev=None):
        raise LLMError("read timed out")

    board = FakeBoard()
    r = pipeline.run_once(CFG, PROMPT, generate=gen, deliver_factory=lambda v, client=None: board)
    assert r.delivered is False
    assert "read timed out" in r.error
    assert board.sent is None


def test_first_attempt_valid_delivers_records_device():
    board = FakeBoard()
    r = pipeline.run_once(
        CFG,
        PROMPT,
        generate=lambda cfg, p, shorter=False, dev=None: "RAIN TODAY",
        deliver_factory=lambda vcfg, client=None: board,
    )
    assert r.device == "note"


def test_vestaboard_device_uses_full_board_and_records_device():
    cfg = AppConfig(
        vestaboard=VestaboardConfig(backend="cloud", cloud_key="k", device="vestaboard")
    )
    board = FakeBoard()
    # Too long for a Note, but fits a full Vestaboard — must deliver, not truncate.
    long_msg = " ".join(["ALERT"] * 8)  # 40 content chars across several lines
    r = pipeline.run_once(
        cfg,
        PROMPT,
        generate=lambda c, p, shorter=False, dev=None: long_msg,
        deliver_factory=lambda v, client=None: board,
    )
    assert r.delivered is True
    assert r.truncated is False
    assert r.device == "vestaboard"
    assert len(r.grid) == 6
    assert all(len(row) == 22 for row in r.grid)
    # The full 6x22 board is what's actually delivered.
    assert len(board.sent) == 6 and all(len(row) == 22 for row in board.sent)


def test_local_backend_not_implemented_reported():
    cfg = AppConfig(
        vestaboard=VestaboardConfig(backend="local", local_endpoint="http://x", local_key="k")
    )
    prompt = PromptEntry(id="1", text="weather", cron="* * * * *")
    r = pipeline.run_once(cfg, prompt, generate=lambda c, p, shorter=False, dev=None: "RAIN TODAY")
    # uses the real make_delivery -> LocalAPI -> NotImplementedError
    assert r.delivered is False
    assert "local" in r.error.lower()
