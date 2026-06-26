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
