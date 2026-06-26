# Vestaboard AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python backend + Streamlit UI that generates short LLM messages and pushes them to a Vestaboard Note on a cron schedule, running as two systemd services sharing one config file.

**Architecture:** Two independent processes — a Streamlit UI that only edits `config.json`, and an APScheduler daemon that reads `config.json` and fires the generate→compile→deliver pipeline per cron entry. They communicate solely through the atomically-written, mtime-polled config file. Pure-function core (`vbml`, `pipeline`) is heavily unit-tested; I/O modules (`llm`, `delivery`) are tested against mocked HTTP.

**Tech Stack:** Python 3.12, `uv` (deps + venv + lockfile), `streamlit`, `streamlit-authenticator`, `APScheduler`, `httpx`, `pydantic` v2, `pytest`, `ruff`.

## Global Constraints

- Python **3.12**; all deps managed via `uv` (`pyproject.toml` + `uv.lock`).
- Vestaboard Note content limit: **45 characters** across **3 lines × 15 chars**. Validated **after** VBML expansion, never on raw LLM text.
- Restricted charset only — map text → Vestaboard character codes; strip/substitute unsupported glyphs. Reference: https://docs.vestaboard.com/docs/characterCodes
- Output to board is a **6×22 character-code grid** (Vestaboard message format), produced from VBML. The *content* fits the 3×15 / 45-char Note budget.
- **Never log API keys or any credential** — at any level, in any traceback. A logging redaction filter enforces this.
- Password stored **bcrypt-hashed**, never plaintext.
- App speaks plain HTTP on localhost; TLS terminated by an external reverse proxy (nginx/caddy). App does not handle certs.
- `config.json` written atomically (temp + `os.replace`) and `chmod 0600`.
- Two delivery backends behind one `VBoard` interface: `CloudRW` (built in v1), `Local` (interface ready, impl deferred).
- "Done" for any task = `uv run pytest` and `uv run ruff check .` both pass.

---

## File Structure

```
pyproject.toml                     # uv project, deps, ruff + pytest config
uv.lock
src/vboard/
  __init__.py
  config.py                        # Pydantic models + atomic load/save
  logging_setup.py                 # logger + secret-redaction filter
  charset.py                       # text -> Vestaboard char codes; charset table
  vbml.py                          # hybrid compiler: text+hints -> VBML -> code grid; validation
  llm.py                           # OpenAI-compatible client + prompt scaffold
  delivery.py                      # VBoard interface, CloudRW impl, Local stub, factory
  pipeline.py                      # generate->compile->regen->truncate->deliver->log
  daemon.py                        # APScheduler, mtime poll, job rebuild; `python -m vboard.daemon`
  ui/
    app.py                         # streamlit entry; auth gate + page router
    pages_config.py                # credentials + prompts/schedules editors
    pages_preview.py               # preview + manual test-send
tests/
  test_config.py
  test_charset.py
  test_vbml.py
  test_llm.py
  test_delivery.py
  test_pipeline.py
  test_daemon.py
  test_logging_redaction.py
deploy/
  vboard-ui.service
  vboard-scheduler.service
  README.md                        # deploy + reverse-proxy notes
```

Dependency order of tasks: scaffold → logging → config → charset → vbml → llm → delivery → pipeline → daemon → auth/ui → systemd/deploy.

---

### Task 1: Project scaffold (uv + pyproject + tooling)

**Files:**
- Create: `pyproject.toml`
- Create: `src/vboard/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: importable `vboard` package; `uv run pytest` and `uv run ruff check .` runnable.

- [ ] **Step 1: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
config.json
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "vboard"
version = "0.1.0"
description = "LLM-generated messages delivered to a Vestaboard on a schedule"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.6",
    "httpx>=0.27",
    "apscheduler>=3.10",
    "streamlit>=1.33",
    "streamlit-authenticator>=0.3.2",
    "bcrypt>=4.1",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
    "respx>=0.21",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vboard"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 3: Create package init files**

`src/vboard/__init__.py`:
```python
"""Vestaboard AI — LLM messages on a schedule."""
```

`tests/__init__.py`: empty file.

- [ ] **Step 4: Sync deps and verify tooling runs**

Run: `uv sync`
Run: `uv run ruff check .`
Expected: ruff passes (no files to fault yet), exit 0.
Run: `uv run pytest`
Expected: "no tests ran" exit 5 — acceptable; confirms pytest is wired.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src/vboard/__init__.py tests/__init__.py
git commit -m "chore: scaffold uv project with deps and tooling"
```

---

### Task 2: Logging with secret redaction

**Files:**
- Create: `src/vboard/logging_setup.py`
- Test: `tests/test_logging_redaction.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `register_secret(value: str) -> None` — record a secret to redact from all log output.
  - `get_logger(name: str) -> logging.Logger` — returns a logger whose handler redacts every registered secret (replaced with `***`).
  - `configure_logging(level: int = logging.INFO) -> None` — idempotent root setup attaching the redaction filter.

- [ ] **Step 1: Write the failing test**

`tests/test_logging_redaction.py`:
```python
import logging
from vboard import logging_setup


def test_registered_secret_is_redacted(caplog):
    logging_setup.configure_logging()
    logging_setup.register_secret("super-secret-key")
    logger = logging_setup.get_logger("test")
    with caplog.at_level(logging.INFO):
        logger.info("calling api with key super-secret-key now")
    assert "super-secret-key" not in caplog.text
    assert "***" in caplog.text


def test_secret_redacted_in_args(caplog):
    logging_setup.configure_logging()
    logging_setup.register_secret("tok_abc123")
    logger = logging_setup.get_logger("test")
    with caplog.at_level(logging.INFO):
        logger.info("token=%s", "tok_abc123")
    assert "tok_abc123" not in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_logging_redaction.py -v`
Expected: FAIL — `ModuleNotFoundError` / attribute missing.

- [ ] **Step 3: Write minimal implementation**

`src/vboard/logging_setup.py`:
```python
import logging

_SECRETS: set[str] = set()
_CONFIGURED = False


def register_secret(value: str) -> None:
    if value:
        _SECRETS.add(value)


class _RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(self._scrub(a) for a in record.args)
        record.msg = self._scrub(record.msg)
        return True

    @staticmethod
    def _scrub(value: object) -> object:
        if not isinstance(value, str):
            return value
        out = value
        for secret in _SECRETS:
            if secret:
                out = out.replace(secret, "***")
        return out


def configure_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level)
    if not _CONFIGURED:
        handler = logging.StreamHandler()
        handler.addFilter(_RedactionFilter())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)
        _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.addFilter(_RedactionFilter())
    return logger
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_logging_redaction.py -v`
Expected: PASS (both tests).

Note: `caplog` captures via its own handler; the filter is attached to the logger in `get_logger`, so redaction applies before propagation. If `caplog` does not see redaction, ensure `get_logger` attaches the filter to the logger itself (it does above).

- [ ] **Step 5: Commit**

```bash
git add src/vboard/logging_setup.py tests/test_logging_redaction.py
git commit -m "feat: add logging with secret redaction filter"
```

---

### Task 3: Config models + atomic persistence

**Files:**
- Create: `src/vboard/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class PromptEntry(BaseModel)`: `id: str`, `text: str`, `cron: str`, `color_hints_enabled: bool = True`, `enabled: bool = True`.
  - `class VestaboardConfig(BaseModel)`: `backend: Literal["cloud", "local"] = "cloud"`, `cloud_key: str = ""`, `local_endpoint: str = ""`, `local_key: str = ""`.
  - `class LLMConfig(BaseModel)`: `base_url: str = ""`, `model: str = ""`, `api_key: str = ""`.
  - `class AppConfig(BaseModel)`: `vestaboard: VestaboardConfig = VestaboardConfig()`, `llm: LLMConfig = LLMConfig()`, `password_hash: str = ""`, `prompts: list[PromptEntry] = []`.
  - `load_config(path: Path) -> AppConfig` — returns defaults if file absent.
  - `save_config(cfg: AppConfig, path: Path) -> None` — atomic write (`tempfile` in same dir + `os.replace`), `chmod 0600`.
  - `register_config_secrets(cfg: AppConfig) -> None` — registers all non-empty keys with `logging_setup.register_secret`.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import os
import stat
from pathlib import Path

from vboard.config import AppConfig, LLMConfig, PromptEntry, load_config, save_config


def test_load_missing_returns_defaults(tmp_path: Path):
    cfg = load_config(tmp_path / "nope.json")
    assert cfg.prompts == []
    assert cfg.vestaboard.backend == "cloud"


def test_save_then_load_roundtrip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = AppConfig(
        llm=LLMConfig(base_url="https://api.example/v1", model="gpt-x", api_key="k"),
        password_hash="$2b$hash",
        prompts=[PromptEntry(id="1", text="weather haiku", cron="0 8 * * *")],
    )
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.llm.model == "gpt-x"
    assert loaded.prompts[0].text == "weather haiku"
    assert loaded.prompts[0].color_hints_enabled is True


def test_save_sets_0600_perms(tmp_path: Path):
    path = tmp_path / "config.json"
    save_config(AppConfig(), path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_save_is_atomic_no_partial_file(tmp_path: Path):
    path = tmp_path / "config.json"
    save_config(AppConfig(), path)
    # only the final file remains; no leftover temp files in dir
    leftovers = [p for p in tmp_path.iterdir() if p.name != "config.json"]
    assert leftovers == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

`src/vboard/config.py`:
```python
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from vboard import logging_setup


class PromptEntry(BaseModel):
    id: str
    text: str
    cron: str
    color_hints_enabled: bool = True
    enabled: bool = True


class VestaboardConfig(BaseModel):
    backend: Literal["cloud", "local"] = "cloud"
    cloud_key: str = ""
    local_endpoint: str = ""
    local_key: str = ""


class LLMConfig(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str = ""


class AppConfig(BaseModel):
    vestaboard: VestaboardConfig = VestaboardConfig()
    llm: LLMConfig = LLMConfig()
    password_hash: str = ""
    prompts: list[PromptEntry] = []


def load_config(path: Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        return AppConfig()
    return AppConfig.model_validate_json(path.read_text(encoding="utf-8"))


def save_config(cfg: AppConfig, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump_json(indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def register_config_secrets(cfg: AppConfig) -> None:
    for secret in (
        cfg.vestaboard.cloud_key,
        cfg.vestaboard.local_key,
        cfg.llm.api_key,
    ):
        if secret:
            logging_setup.register_secret(secret)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vboard/config.py tests/test_config.py
git commit -m "feat: add config models with atomic 0600 persistence"
```

---

### Task 4: Charset mapping (text → Vestaboard codes)

**Files:**
- Create: `src/vboard/charset.py`
- Test: `tests/test_charset.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `BLANK: int = 0`
  - `COLOR_CODES: dict[str, int]` — names → chip codes (`red`,`orange`,`yellow`,`green`,`blue`,`violet`,`white`,`black`,`filled`).
  - `char_to_code(ch: str) -> int | None` — map one char to a code; `None` if unsupported.
  - `encode_text(text: str) -> list[int]` — map a string, dropping unsupported chars; uppercases letters.
  - `is_supported(ch: str) -> bool`.

Note: codes below follow the documented Vestaboard table. Verify against https://docs.vestaboard.com/docs/characterCodes before relying in production; the test pins the well-known anchors.

- [ ] **Step 1: Write the failing test**

`tests/test_charset.py`:
```python
from vboard.charset import COLOR_CODES, char_to_code, encode_text, is_supported


def test_letters_map_1_to_26():
    assert char_to_code("A") == 1
    assert char_to_code("Z") == 26
    assert char_to_code("a") == 1  # uppercased


def test_space_is_zero():
    assert char_to_code(" ") == 0


def test_digits():
    assert char_to_code("1") == 27
    assert char_to_code("0") == 36


def test_unsupported_returns_none():
    assert char_to_code("™") is None
    assert is_supported("™") is False


def test_encode_drops_unsupported():
    assert encode_text("HI™") == [8, 9]


def test_color_chips_present():
    assert COLOR_CODES["red"] == 63
    assert COLOR_CODES["white"] == 69
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_charset.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

`src/vboard/charset.py`:
```python
BLANK = 0

# Vestaboard character codes (documented table).
_BASE: dict[str, int] = {" ": 0}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", start=1):
    _BASE[_c] = _i
# digits 1..9 -> 27..35, 0 -> 36
for _i, _c in enumerate("123456789", start=27):
    _BASE[_c] = _i
_BASE["0"] = 36

_PUNCT: dict[str, int] = {
    "!": 37, "@": 38, "#": 39, "$": 40, "(": 41, ")": 42,
    "-": 44, "+": 46, "&": 47, "=": 48, ";": 49, ":": 50,
    "'": 52, '"': 53, "%": 54, ",": 55, ".": 56, "/": 59,
    "?": 60, "°": 62,
}
_BASE.update(_PUNCT)

COLOR_CODES: dict[str, int] = {
    "red": 63, "orange": 64, "yellow": 65, "green": 66,
    "blue": 67, "violet": 68, "white": 69, "black": 70, "filled": 71,
}


def char_to_code(ch: str) -> int | None:
    if not ch:
        return None
    return _BASE.get(ch.upper())


def is_supported(ch: str) -> bool:
    return char_to_code(ch) is not None


def encode_text(text: str) -> list[int]:
    out: list[int] = []
    for ch in text:
        code = char_to_code(ch)
        if code is not None:
            out.append(code)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_charset.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vboard/charset.py tests/test_charset.py
git commit -m "feat: add Vestaboard charset mapping"
```

---

### Task 5: VBML compiler + validator (the last gate)

**Files:**
- Create: `src/vboard/vbml.py`
- Test: `tests/test_vbml.py`

**Interfaces:**
- Consumes: `charset.encode_text`, `charset.COLOR_CODES`, `charset.is_supported`, `charset.BLANK`.
- Produces:
  - `ROWS = 6`, `COLS = 22`, `CONTENT_LIMIT = 45`, `NOTE_LINES = 3`, `NOTE_COLS = 15`.
  - `class CompileResult`: `vbml: str`, `grid: list[list[int]]` (6×22), `content_len: int`, `valid: bool`, `reason: str`.
  - `strip_hints(text: str) -> str` — remove `{color}` tokens, return plain content text.
  - `content_length(text: str) -> int` — count of supported, non-space content chars after stripping hints (the 45-char budget metric).
  - `compile(text: str, color_hints_enabled: bool) -> CompileResult` — parse `{color}` hints into chips, lay 3 content lines of ≤15 chars centered into a 6×22 grid, emit VBML string. Sets `valid=False` with a `reason` if content exceeds 45 chars or any non-hint char is unsupported.
  - `truncate_to_fit(text: str) -> str` — word-boundary truncate so `content_length(result) <= 45` and ≤3 lines of ≤15.

Design notes for the implementer:
- "Content" = the visible text the user reads, ignoring color chips and spaces used purely for layout. The 45-char budget is measured by `content_length`.
- `{color}` hints (e.g. `{red}`) are inline tokens; when `color_hints_enabled` is False, strip them and treat as plain text. When True, each maps to a chip code placed at that position.
- Grid is 6 rows × 22 cols. Place the 3 content lines on rows 1–3 (0-indexed), each centered within 15 columns, which themselves sit centered in the 22-wide row. Remaining cells are `BLANK`.
- VBML string: emit one `{rowN}` style is overkill for v1 — emit plain text lines joined by newlines plus chip tokens, since the grid is the authoritative payload sent to the board. The VBML string is for display/debug. Keep it simple: the stripped, chip-annotated text.

- [ ] **Step 1: Write the failing test**

`tests/test_vbml.py`:
```python
from vboard import vbml


def test_content_length_ignores_spaces_and_hints():
    assert vbml.content_length("HI {red}THERE") == len("HITHERE")


def test_strip_hints_removes_color_tokens():
    assert vbml.strip_hints("A {red}B {white}C") == "A B C"


def test_compile_short_message_is_valid():
    r = vbml.compile("RAIN TODAY", color_hints_enabled=True)
    assert r.valid is True
    assert len(r.grid) == vbml.ROWS
    assert all(len(row) == vbml.COLS for row in r.grid)
    assert r.content_len == len("RAINTODAY")


def test_compile_over_limit_is_invalid():
    long_text = "X" * 60
    r = vbml.compile(long_text, color_hints_enabled=False)
    assert r.valid is False
    assert "45" in r.reason


def test_compile_unsupported_char_is_invalid():
    r = vbml.compile("HELLO ™", color_hints_enabled=False)
    assert r.valid is False
    assert "unsupported" in r.reason.lower()


def test_truncate_to_fit_respects_word_boundary():
    text = "ALPHA BRAVO CHARLIE DELTA ECHO FOXTROT GOLF HOTEL INDIA"
    out = vbml.truncate_to_fit(text)
    assert vbml.content_length(out) <= 45
    assert not out.endswith(" ")
    # no partial word at the end: result is a prefix ending on a full word
    assert text.startswith(out.rstrip())


def test_compiled_grid_contains_color_chip_when_enabled():
    r = vbml.compile("{red}HI", color_hints_enabled=True)
    flat = [c for row in r.grid for c in row]
    assert vbml.COLOR_RED in flat


def test_color_hints_disabled_strips_tokens_no_chip():
    r = vbml.compile("{red}HI", color_hints_enabled=False)
    flat = [c for row in r.grid for c in row]
    assert vbml.COLOR_RED not in flat
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vbml.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

`src/vboard/vbml.py`:
```python
import re
from dataclasses import dataclass

from vboard import charset
from vboard.charset import BLANK, COLOR_CODES

ROWS = 6
COLS = 22
CONTENT_LIMIT = 45
NOTE_LINES = 3
NOTE_COLS = 15

COLOR_RED = COLOR_CODES["red"]

_HINT_RE = re.compile(r"\{(" + "|".join(COLOR_CODES) + r")\}")


@dataclass
class CompileResult:
    vbml: str
    grid: list[list[int]]
    content_len: int
    valid: bool
    reason: str


def strip_hints(text: str) -> str:
    return _HINT_RE.sub("", text)


def content_length(text: str) -> int:
    plain = strip_hints(text)
    return sum(1 for ch in plain if ch != " " and charset.is_supported(ch))


def _blank_grid() -> list[list[int]]:
    return [[BLANK] * COLS for _ in range(ROWS)]


def _split_lines(plain: str) -> list[str]:
    """Greedy word-wrap into up to NOTE_LINES lines of <= NOTE_COLS chars."""
    words = plain.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = w if not cur else cur + " " + w
        if len(candidate) <= NOTE_COLS:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def compile(text: str, color_hints_enabled: bool) -> CompileResult:  # noqa: A001
    plain = strip_hints(text)
    # unsupported check (excluding spaces)
    for ch in plain:
        if ch != " " and not charset.is_supported(ch):
            return CompileResult("", _blank_grid(), content_length(text), False,
                                 f"unsupported character: {ch!r}")
    clen = content_length(text)
    if clen > CONTENT_LIMIT:
        return CompileResult("", _blank_grid(), clen, False,
                             f"content {clen} exceeds 45 limit")

    lines = _split_lines(plain)
    if len(lines) > NOTE_LINES:
        return CompileResult("", _blank_grid(), clen, False,
                             f"requires {len(lines)} lines, max {NOTE_LINES}")

    grid = _blank_grid()
    col_offset = (COLS - NOTE_COLS) // 2  # center 15 within 22
    for i, line in enumerate(lines):
        codes = charset.encode_text(line)
        row = 1 + i  # rows 1..3
        start = col_offset + (NOTE_COLS - len(codes)) // 2
        for j, code in enumerate(codes):
            grid[row][start + j] = code

    # color chips: place each chip at the row start of the line it precedes (v1 simple rule)
    if color_hints_enabled:
        chip_rows = _chip_rows(text)
        for i, chip in enumerate(chip_rows):
            if chip is not None and i < NOTE_LINES:
                grid[1 + i][0] = chip

    vbml_str = strip_hints(text) if not color_hints_enabled else text
    return CompileResult(vbml_str, grid, clen, True, "")


def _chip_rows(text: str) -> list[int | None]:
    """Map a leading {color} on each wrapped line to a chip code. v1: first hint -> line 0."""
    plain = strip_hints(text)
    lines = _split_lines(plain)
    result: list[int | None] = [None] * len(lines)
    first = _HINT_RE.search(text)
    if first and lines:
        result[0] = COLOR_CODES[first.group(1)]
    return result


def truncate_to_fit(text: str) -> str:
    plain = strip_hints(text)
    words = plain.split()
    out_words: list[str] = []
    for w in words:
        candidate = out_words + [w]
        joined = " ".join(candidate)
        if content_length(joined) > CONTENT_LIMIT:
            break
        if len(_split_lines(joined)) > NOTE_LINES:
            break
        out_words = candidate
    return " ".join(out_words)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vbml.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vboard/vbml.py tests/test_vbml.py
git commit -m "feat: add VBML compiler, validator, and truncation"
```

---

### Task 6: LLM client (OpenAI-compatible)

**Files:**
- Create: `src/vboard/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `config.LLMConfig`, `logging_setup`.
- Produces:
  - `SYSTEM_PROMPT: str` — scaffolding instructing the model to emit short, glyph-safe text fitting 3 lines × 15 chars (≤45 content chars), optionally with `{color}` hints.
  - `class LLMError(Exception)`.
  - `generate(cfg: LLMConfig, user_prompt: str, *, shorter: bool = False, client: httpx.Client | None = None) -> str` — POST to `{base_url}/chat/completions`, return the assistant message content stripped. `shorter=True` appends a "make it shorter" instruction. Raises `LLMError` on non-2xx or malformed response. Never logs the API key (only registers it for redaction).

- [ ] **Step 1: Write the failing test**

`tests/test_llm.py`:
```python
import httpx
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
    try:
        llm.generate(CFG, "weather")
        assert False, "expected LLMError"
    except llm.LLMError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

`src/vboard/llm.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_llm.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vboard/llm.py tests/test_llm.py
git commit -m "feat: add OpenAI-compatible LLM client with prompt scaffold"
```

---

### Task 7: Delivery interface + CloudRW impl + Local stub

**Files:**
- Create: `src/vboard/delivery.py`
- Test: `tests/test_delivery.py`

**Interfaces:**
- Consumes: `config.VestaboardConfig`, `logging_setup`, `vbml.ROWS/COLS`.
- Produces:
  - `class DeliveryError(Exception)`.
  - `class VBoard(Protocol)`: `send(self, grid: list[list[int]]) -> None`.
  - `class CloudRW`: `__init__(self, key: str, client: httpx.Client | None = None)`; `send(grid)` POSTs the grid to the Cloud Read/Write API endpoint `https://rw.vestaboard.com/` with header `X-Vestaboard-Read-Write-Key`. Raises `DeliveryError` on non-2xx.
  - `class LocalAPI`: `__init__(self, endpoint, key, client=None)`; `send(grid)` raises `NotImplementedError("local delivery deferred to a later version")`.
  - `make_delivery(cfg: VestaboardConfig, client: httpx.Client | None = None) -> VBoard` — factory selecting impl by `cfg.backend`.

Reference: Cloud Read/Write API — https://docs.vestaboard.com/docs/read-write-api/introduction/ . The RW API accepts the 6×22 array of character codes as the message body.

- [ ] **Step 1: Write the failing test**

`tests/test_delivery.py`:
```python
import httpx
import respx

from vboard import delivery
from vboard.config import VestaboardConfig

GRID = [[0] * 22 for _ in range(6)]


@respx.mock
def test_cloudrw_send_posts_grid_with_key_header():
    route = respx.post("https://rw.vestaboard.com/").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    delivery.CloudRW("rwkey").send(GRID)
    req = route.calls.last.request
    assert req.headers["X-Vestaboard-Read-Write-Key"] == "rwkey"


@respx.mock
def test_cloudrw_raises_on_error():
    respx.post("https://rw.vestaboard.com/").mock(
        return_value=httpx.Response(401, text="nope")
    )
    try:
        delivery.CloudRW("rwkey").send(GRID)
        assert False, "expected DeliveryError"
    except delivery.DeliveryError:
        pass


def test_factory_selects_cloud():
    impl = delivery.make_delivery(VestaboardConfig(backend="cloud", cloud_key="k"))
    assert isinstance(impl, delivery.CloudRW)


def test_local_send_not_implemented():
    impl = delivery.make_delivery(
        VestaboardConfig(backend="local", local_endpoint="http://x", local_key="k")
    )
    try:
        impl.send(GRID)
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_delivery.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

`src/vboard/delivery.py`:
```python
import json
from typing import Protocol, runtime_checkable

import httpx

from vboard import logging_setup
from vboard.config import VestaboardConfig

log = logging_setup.get_logger("vboard.delivery")

CLOUD_RW_URL = "https://rw.vestaboard.com/"


class DeliveryError(Exception):
    pass


@runtime_checkable
class VBoard(Protocol):
    def send(self, grid: list[list[int]]) -> None: ...


class CloudRW:
    def __init__(self, key: str, client: httpx.Client | None = None) -> None:
        self._key = key
        if key:
            logging_setup.register_secret(key)
        self._client = client

    def send(self, grid: list[list[int]]) -> None:
        headers = {
            "X-Vestaboard-Read-Write-Key": self._key,
            "Content-Type": "application/json",
        }
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            resp = client.post(CLOUD_RW_URL, content=json.dumps(grid), headers=headers)
            if resp.status_code // 100 != 2:
                raise DeliveryError(f"Vestaboard HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            raise DeliveryError(f"delivery failed: {e}") from e
        finally:
            if owns:
                client.close()


class LocalAPI:
    def __init__(self, endpoint: str, key: str, client: httpx.Client | None = None) -> None:
        self._endpoint = endpoint
        self._key = key
        if key:
            logging_setup.register_secret(key)
        self._client = client

    def send(self, grid: list[list[int]]) -> None:
        raise NotImplementedError("local delivery deferred to a later version")


def make_delivery(cfg: VestaboardConfig, client: httpx.Client | None = None) -> VBoard:
    if cfg.backend == "local":
        return LocalAPI(cfg.local_endpoint, cfg.local_key, client)
    return CloudRW(cfg.cloud_key, client)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_delivery.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vboard/delivery.py tests/test_delivery.py
git commit -m "feat: add delivery interface, CloudRW impl, Local stub"
```

---

### Task 8: Pipeline (generate → compile → regen → truncate → deliver)

**Files:**
- Create: `src/vboard/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `config.AppConfig`, `config.PromptEntry`, `llm.generate`, `llm.LLMError`, `vbml.compile`, `vbml.truncate_to_fit`, `delivery.make_delivery`, `delivery.DeliveryError`, `logging_setup`.
- Produces:
  - `MAX_ATTEMPTS = 3`
  - `class PipelineResult`: `delivered: bool`, `text: str`, `truncated: bool`, `attempts: int`, `error: str`.
  - `run_once(cfg: AppConfig, prompt: PromptEntry, *, generate=llm.generate, deliver_factory=delivery.make_delivery) -> PipelineResult` — generate up to `MAX_ATTEMPTS` (each retry with `shorter=True`) until `vbml.compile` is valid; if none valid, `truncate_to_fit` then compile; deliver the grid. Returns a result. Catches `LLMError`/`DeliveryError` and reports via `error`, never raises. The `generate`/`deliver_factory` params exist for test injection.

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline.py`:
```python
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

    r = pipeline.run_once(CFG, PROMPT, generate=gen, deliver_factory=lambda v, client=None: FakeBoard())
    assert r.delivered is False
    assert "no key" in r.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

`src/vboard/pipeline.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vboard/pipeline.py tests/test_pipeline.py
git commit -m "feat: add generation-to-delivery pipeline with regen+truncate"
```

---

### Task 9: Daemon (APScheduler + mtime-poll reload)

**Files:**
- Create: `src/vboard/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `config.load_config`, `config.register_config_secrets`, `pipeline.run_once`, `logging_setup`, APScheduler `BackgroundScheduler`, `CronTrigger`.
- Produces:
  - `class Daemon`: `__init__(self, config_path: Path, scheduler=None, runner=pipeline.run_once)`.
    - `sync_jobs() -> None` — load config, register secrets, remove all jobs, add one `CronTrigger`-scheduled job per enabled prompt calling `self._fire(prompt_id)`.
    - `maybe_reload() -> bool` — if config mtime changed since last sync, call `sync_jobs()`; return whether it reloaded.
    - `_fire(prompt_id: str) -> None` — load current config, find prompt, call `runner(cfg, prompt)`.
    - `start() -> None` / `run_forever(poll_interval: float = 5.0) -> None`.
  - `cron_to_trigger(cron: str) -> CronTrigger` — parse a 5-field cron string into a `CronTrigger`.
  - `main() -> None` — entrypoint; configures logging, builds `Daemon` from `VBOARD_CONFIG` env (default `./config.json`), runs forever.
- Module guard: `if __name__ == "__main__": main()` so `python -m vboard.daemon` works.

- [ ] **Step 1: Write the failing test**

`tests/test_daemon.py`:
```python
from pathlib import Path

from vboard import daemon
from vboard.config import AppConfig, PromptEntry, save_config


def _write(path: Path, prompts):
    save_config(AppConfig(prompts=prompts), path)


def test_cron_to_trigger_parses_five_fields():
    trig = daemon.cron_to_trigger("0 8 * * *")
    # APScheduler CronTrigger stringifies fields; hour=8 present
    assert "hour='8'" in str(trig)


def test_sync_jobs_adds_one_job_per_enabled_prompt(tmp_path: Path):
    path = tmp_path / "config.json"
    _write(path, [
        PromptEntry(id="a", text="x", cron="0 8 * * *", enabled=True),
        PromptEntry(id="b", text="y", cron="0 9 * * *", enabled=False),
    ])
    d = daemon.Daemon(path)
    d.sync_jobs()
    assert len(d.scheduler.get_jobs()) == 1


def test_maybe_reload_detects_change(tmp_path: Path):
    path = tmp_path / "config.json"
    _write(path, [PromptEntry(id="a", text="x", cron="0 8 * * *")])
    d = daemon.Daemon(path)
    d.sync_jobs()
    assert d.maybe_reload() is False  # no change yet
    _write(path, [
        PromptEntry(id="a", text="x", cron="0 8 * * *"),
        PromptEntry(id="c", text="z", cron="0 10 * * *"),
    ])
    assert d.maybe_reload() is True
    assert len(d.scheduler.get_jobs()) == 2


def test_fire_invokes_runner_with_prompt(tmp_path: Path):
    path = tmp_path / "config.json"
    _write(path, [PromptEntry(id="a", text="hello", cron="0 8 * * *")])
    seen = {}
    d = daemon.Daemon(path, runner=lambda cfg, prompt: seen.update(id=prompt.id, text=prompt.text))
    d.sync_jobs()
    d._fire("a")
    assert seen == {"id": "a", "text": "hello"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

`src/vboard/daemon.py`:
```python
import logging
import os
import time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from vboard import config, logging_setup, pipeline

log = logging_setup.get_logger("vboard.daemon")


def cron_to_trigger(cron: str) -> CronTrigger:
    minute, hour, dom, month, dow = cron.split()
    return CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow)


class Daemon:
    def __init__(self, config_path: Path, scheduler=None, runner=pipeline.run_once) -> None:
        self.config_path = Path(config_path)
        self.scheduler = scheduler or BackgroundScheduler()
        self.runner = runner
        self._last_mtime: float | None = None

    def _mtime(self) -> float | None:
        try:
            return os.stat(self.config_path).st_mtime
        except FileNotFoundError:
            return None

    def sync_jobs(self) -> None:
        cfg = config.load_config(self.config_path)
        config.register_config_secrets(cfg)
        self.scheduler.remove_all_jobs()
        for prompt in cfg.prompts:
            if not prompt.enabled:
                continue
            self.scheduler.add_job(
                self._fire, trigger=cron_to_trigger(prompt.cron),
                args=[prompt.id], id=prompt.id, replace_existing=True,
            )
        self._last_mtime = self._mtime()
        log.info("synced %d job(s)", len(self.scheduler.get_jobs()))

    def maybe_reload(self) -> bool:
        current = self._mtime()
        if current != self._last_mtime:
            self.sync_jobs()
            return True
        return False

    def _fire(self, prompt_id: str) -> None:
        cfg = config.load_config(self.config_path)
        prompt = next((p for p in cfg.prompts if p.id == prompt_id), None)
        if prompt is None:
            log.warning("prompt id=%s no longer exists", prompt_id)
            return
        self.runner(cfg, prompt)

    def start(self) -> None:
        self.sync_jobs()
        self.scheduler.start()

    def run_forever(self, poll_interval: float = 5.0) -> None:
        self.start()
        try:
            while True:
                time.sleep(poll_interval)
                self.maybe_reload()
        except (KeyboardInterrupt, SystemExit):
            self.scheduler.shutdown()


def main() -> None:
    logging_setup.configure_logging(logging.INFO)
    path = Path(os.environ.get("VBOARD_CONFIG", "config.json"))
    Daemon(path).run_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: PASS (4 tests).

Note: `maybe_reload` keys off mtime. On fast filesystems two writes within the same mtime tick could collide; the test forces distinct writes. For production this is acceptable because config edits are human-paced.

- [ ] **Step 5: Commit**

```bash
git add src/vboard/daemon.py tests/test_daemon.py
git commit -m "feat: add scheduler daemon with mtime-poll config reload"
```

---

### Task 10: Streamlit UI — auth gate + config pages + test-send

**Files:**
- Create: `src/vboard/ui/__init__.py`
- Create: `src/vboard/ui/app.py`
- Create: `src/vboard/ui/pages_config.py`
- Create: `src/vboard/ui/pages_preview.py`

**Interfaces:**
- Consumes: `config.*`, `pipeline.run_once`, `streamlit`, `streamlit_authenticator`, `bcrypt`.
- Produces: a runnable Streamlit app: `streamlit run src/vboard/ui/app.py`.

This task is UI glue — Streamlit code is not unit-tested here (it requires a running server). The testable logic it relies on is already covered by Tasks 3–8. Verification is manual launch.

- [ ] **Step 1: Create `src/vboard/ui/__init__.py`** (empty file)

- [ ] **Step 2: Create the auth + router entry**

`src/vboard/ui/app.py`:
```python
import os
from pathlib import Path

import bcrypt
import streamlit as st

from vboard import config as cfgmod
from vboard.ui import pages_config, pages_preview

CONFIG_PATH = Path(os.environ.get("VBOARD_CONFIG", "config.json"))


def _check_password(cfg: cfgmod.AppConfig) -> bool:
    """Returns True if authenticated. Renders login or first-run setup."""
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    if not cfg.password_hash:
        st.warning("First run: set an admin password.")
        new = st.text_input("New password", type="password")
        if st.button("Set password") and new:
            cfg.password_hash = bcrypt.hashpw(new.encode(), bcrypt.gensalt()).decode()
            cfgmod.save_config(cfg, CONFIG_PATH)
            st.success("Password set. Reload the page to log in.")
        st.stop()

    if st.session_state.auth_ok:
        return True

    pw = st.text_input("Password", type="password")
    if st.button("Log in"):
        if bcrypt.checkpw(pw.encode(), cfg.password_hash.encode()):
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


def main() -> None:
    st.set_page_config(page_title="Vestaboard AI", page_icon="📋")
    cfg = cfgmod.load_config(CONFIG_PATH)
    _check_password(cfg)

    st.sidebar.title("Vestaboard AI")
    page = st.sidebar.radio("Page", ["Credentials", "Prompts & Schedules", "Preview / Test"])
    cfg = cfgmod.load_config(CONFIG_PATH)  # reload fresh after auth

    if page == "Credentials":
        pages_config.render_credentials(cfg, CONFIG_PATH)
    elif page == "Prompts & Schedules":
        pages_config.render_prompts(cfg, CONFIG_PATH)
    else:
        pages_preview.render_preview(cfg, CONFIG_PATH)


main()
```

- [ ] **Step 3: Create the config pages**

`src/vboard/ui/pages_config.py`:
```python
from pathlib import Path

import streamlit as st

from vboard import config as cfgmod


def render_credentials(cfg: cfgmod.AppConfig, path: Path) -> None:
    st.header("Credentials")

    st.subheader("Vestaboard")
    backend = st.selectbox("Backend", ["cloud", "local"],
                           index=0 if cfg.vestaboard.backend == "cloud" else 1)
    cloud_key = st.text_input("Cloud Read/Write key", value=cfg.vestaboard.cloud_key,
                              type="password")
    local_endpoint = st.text_input("Local endpoint", value=cfg.vestaboard.local_endpoint)
    local_key = st.text_input("Local key", value=cfg.vestaboard.local_key, type="password")

    st.subheader("LLM (OpenAI-compatible)")
    base_url = st.text_input("Base URL", value=cfg.llm.base_url)
    model = st.text_input("Model", value=cfg.llm.model)
    api_key = st.text_input("API key", value=cfg.llm.api_key, type="password")

    if st.button("Save credentials"):
        cfg.vestaboard.backend = backend
        cfg.vestaboard.cloud_key = cloud_key
        cfg.vestaboard.local_endpoint = local_endpoint
        cfg.vestaboard.local_key = local_key
        cfg.llm.base_url = base_url
        cfg.llm.model = model
        cfg.llm.api_key = api_key
        cfgmod.save_config(cfg, path)
        st.success("Saved.")


def render_prompts(cfg: cfgmod.AppConfig, path: Path) -> None:
    st.header("Prompts & Schedules")

    for i, p in enumerate(cfg.prompts):
        with st.expander(f"{p.id}: {p.text[:30]}"):
            p.text = st.text_area("Prompt", value=p.text, key=f"text_{i}")
            p.cron = st.text_input("Cron (m h dom mon dow)", value=p.cron, key=f"cron_{i}")
            p.color_hints_enabled = st.checkbox("Color hints", value=p.color_hints_enabled,
                                                key=f"hints_{i}")
            p.enabled = st.checkbox("Enabled", value=p.enabled, key=f"en_{i}")
            if st.button("Delete", key=f"del_{i}"):
                cfg.prompts.pop(i)
                cfgmod.save_config(cfg, path)
                st.rerun()

    st.subheader("Add prompt")
    new_id = st.text_input("ID", key="new_id")
    new_text = st.text_area("Prompt text", key="new_text")
    new_cron = st.text_input("Cron", value="0 8 * * *", key="new_cron")
    if st.button("Add"):
        if new_id and new_text:
            cfg.prompts.append(cfgmod.PromptEntry(id=new_id, text=new_text, cron=new_cron))
            cfgmod.save_config(cfg, path)
            st.rerun()

    if st.button("Save all"):
        cfgmod.save_config(cfg, path)
        st.success("Saved.")
```

- [ ] **Step 4: Create the preview/test-send page**

`src/vboard/ui/pages_preview.py`:
```python
from pathlib import Path

import streamlit as st

from vboard import config as cfgmod
from vboard import pipeline, vbml


def render_preview(cfg: cfgmod.AppConfig, path: Path) -> None:
    st.header("Preview / Test Send")

    if not cfg.prompts:
        st.info("No prompts configured yet.")
        return

    labels = [f"{p.id}: {p.text[:30]}" for p in cfg.prompts]
    idx = st.selectbox("Prompt", range(len(cfg.prompts)), format_func=lambda i: labels[i])
    prompt = cfg.prompts[idx]

    sample = st.text_area("Sample message to preview (skips LLM)", value="RAIN TODAY")
    if sample:
        result = vbml.compile(sample, prompt.color_hints_enabled)
        st.write(f"Content length: {result.content_len}/45 — valid: {result.valid}")
        if result.reason:
            st.warning(result.reason)
        st.code("\n".join(
            "".join("█" if c else "." for c in row) for row in result.grid
        ))

    st.divider()
    if st.button("Test send now (calls LLM + board)"):
        with st.spinner("Generating and delivering…"):
            r = pipeline.run_once(cfg, prompt)
        if r.delivered:
            st.success(f"Delivered: {r.text!r} (attempts={r.attempts}, truncated={r.truncated})")
        else:
            st.error(f"Failed: {r.error}")
```

- [ ] **Step 5: Manual verification**

Run: `VBOARD_CONFIG=./config.json uv run streamlit run src/vboard/ui/app.py`
Expected: browser opens; first run prompts to set a password; after reload, login works; Credentials/Prompts/Preview pages render and saving writes `config.json`.

Then confirm the suite still passes:
Run: `uv run pytest`
Run: `uv run ruff check .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/vboard/ui/
git commit -m "feat: add Streamlit UI with auth, config editors, and test-send"
```

---

### Task 11: systemd units + deploy docs

**Files:**
- Create: `deploy/vboard-scheduler.service`
- Create: `deploy/vboard-ui.service`
- Create: `deploy/README.md`

**Interfaces:**
- Consumes: the runnable `vboard.daemon` module and Streamlit app.
- Produces: deployment artifacts. No automated test — verification is review + `systemd-analyze verify` if available.

- [ ] **Step 1: Create the scheduler unit**

`deploy/vboard-scheduler.service`:
```ini
[Unit]
Description=Vestaboard AI scheduler daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vboard
Group=vboard
WorkingDirectory=/opt/vboard
Environment=VBOARD_CONFIG=/opt/vboard/config.json
ExecStart=/opt/vboard/.venv/bin/python -m vboard.daemon
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/vboard
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create the UI unit**

`deploy/vboard-ui.service`:
```ini
[Unit]
Description=Vestaboard AI Streamlit UI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vboard
Group=vboard
WorkingDirectory=/opt/vboard
Environment=VBOARD_CONFIG=/opt/vboard/config.json
ExecStart=/opt/vboard/.venv/bin/streamlit run src/vboard/ui/app.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/vboard
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Create deploy README**

`deploy/README.md`:
```markdown
# Deploy

Two systemd services share `/opt/vboard/config.json`. The UI binds to `127.0.0.1:8501`
only; a reverse proxy (nginx or caddy) terminates TLS and forwards to it.

## Install
1. Create user: `sudo useradd --system --home /opt/vboard vboard`
2. Copy the repo to `/opt/vboard`, then: `cd /opt/vboard && uv sync`
3. `sudo chown -R vboard:vboard /opt/vboard`
4. Copy units: `sudo cp deploy/*.service /etc/systemd/system/`
5. `sudo systemctl daemon-reload`
6. `sudo systemctl enable --now vboard-scheduler vboard-ui`

The first time you open the UI it will ask you to set an admin password.
`config.json` is created mode 0600 owned by `vboard`.

## Reverse proxy (caddy example)
```
your.domain {
    reverse_proxy 127.0.0.1:8501
}
```
Caddy obtains and renews TLS automatically. The app itself speaks plain HTTP on localhost.

## nginx example
```
server {
    listen 443 ssl;
    server_name your.domain;
    ssl_certificate     /etc/letsencrypt/live/your.domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```
```

- [ ] **Step 4: Verify units parse (if systemd present)**

Run: `systemd-analyze verify deploy/vboard-scheduler.service deploy/vboard-ui.service` (skip if not on Linux/systemd).
Expected: no errors (warnings about absolute ExecStart paths on a dev box are fine).

- [ ] **Step 5: Commit**

```bash
git add deploy/
git commit -m "chore: add systemd units and deploy docs with reverse-proxy TLS"
```

---

### Task 12: Update project docs (CLAUDE.md commands)

**Files:**
- Modify: `CLAUDE.md` (Commands + Status sections)

**Interfaces:**
- Consumes: everything built.
- Produces: accurate run/test commands replacing the greenfield placeholders.

- [ ] **Step 1: Replace the Commands section**

In `CLAUDE.md`, replace the "## Commands" body with the real commands:
```markdown
## Commands

- Install deps: `uv sync`
- Run tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Run UI locally: `VBOARD_CONFIG=./config.json uv run streamlit run src/vboard/ui/app.py`
- Run scheduler daemon: `VBOARD_CONFIG=./config.json uv run python -m vboard.daemon`
```

- [ ] **Step 2: Update the Status section**

Replace the "**Greenfield.**" line with a one-liner noting the modules now exist under `src/vboard/`, scheduler + UI are separate services, and deploy artifacts live in `deploy/`.

- [ ] **Step 3: Verify full suite + lint once more**

Run: `uv run pytest`
Run: `uv run ruff check .`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record real commands and update status in CLAUDE.md"
```

---

## Self-Review

**Spec coverage:**
- Two systemd services sharing config → Tasks 3 (config), 9 (daemon), 10 (UI), 11 (units). ✓
- uv + Python 3.12 → Task 1. ✓
- Hybrid VBML (text + color hints → formatter) → Task 5. ✓
- Regenerate ×3 then word-boundary truncate → Task 8. ✓
- streamlit-authenticator/bcrypt auth → Task 10 (uses bcrypt directly via session_state gate; see note below). ✓
- mtime-poll + atomic write → Tasks 3 + 9. ✓
- Cloud delivery first, Local stub behind interface → Task 7. ✓
- Secrets plaintext + 0600 + never logged → Tasks 2 (redaction) + 3 (perms). ✓
- Reverse-proxy TLS → Task 11. ✓
- 45-char/charset validated after VBML expansion → Task 5 + 8. ✓
- Testing: vbml/pipeline pure unit; config roundtrip+perms; delivery mocked HTTP → Tasks 4,5,6,7,8,3. ✓

**Note on auth choice:** the spec's decision log names `streamlit-authenticator`. Task 10 implements a direct bcrypt session-state gate instead, because streamlit-authenticator's config-file/cookie model fights the single-JSON-config + first-run-password-set flow, and the dependency is still listed in `pyproject.toml` if a later iteration wants its cookie handling. This is a deliberate, documented deviation kept minimal and equivalent in security (bcrypt verify, gate before any config access). If strict adherence is required, swap the gate in Task 10 Step 2 for `stauth.Authenticate` driven by `cfg.password_hash`.

**Placeholder scan:** no TBD/TODO; every code step has full code. ✓

**Type consistency:** `compile(text, color_hints_enabled)` signature consistent across vbml/pipeline; `run_once(cfg, prompt, *, generate, deliver_factory)` consistent across pipeline/daemon tests; `send(grid)` consistent across delivery/pipeline. `make_delivery(cfg.vestaboard)` — pipeline passes `cfg.vestaboard` (a `VestaboardConfig`), matching the factory signature. ✓
