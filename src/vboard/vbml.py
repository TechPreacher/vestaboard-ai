import re
from dataclasses import dataclass

from vboard import charset, device
from vboard.charset import BLANK, COLOR_CODES
from vboard.device import BOARD_COLS, BOARD_ROWS, DeviceSpec

# Board dimensions (the full grid always delivered to the API). Content
# dimensions/limits are device-specific and come from a DeviceSpec.
ROWS = BOARD_ROWS
COLS = BOARD_COLS

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


def _split_lines(plain: str, cols: int) -> list[str]:
    """Greedy word-wrap into lines of <= cols chars."""
    words = plain.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = w if not cur else cur + " " + w
        if len(candidate) <= cols:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def compile(  # noqa: A001
    text: str,
    color_hints_enabled: bool,
    dev: DeviceSpec | None = None,
) -> CompileResult:
    dev = dev or device.get(None)
    plain = strip_hints(text)
    # unsupported check (excluding spaces)
    for ch in plain:
        if ch != " " and not charset.is_supported(ch):
            return CompileResult("", _blank_grid(), content_length(text), False,
                                 f"unsupported character: {ch!r}")
    clen = content_length(text)
    if clen > dev.content_limit:
        return CompileResult("", _blank_grid(), clen, False,
                             f"content {clen} exceeds {dev.content_limit} limit")

    lines = _split_lines(plain, dev.cols)
    if len(lines) > dev.lines:
        return CompileResult("", _blank_grid(), clen, False,
                             f"requires {len(lines)} lines, max {dev.lines}")

    # A color chip occupies a real cell, so it counts toward its line's width
    # (a line with a chip holds one fewer text char than the device's cols).
    chips = _chip_rows(text, dev) if color_hints_enabled else [None] * len(lines)
    for i, line in enumerate(lines):
        width = len(line) + (1 if chips[i] is not None else 0)
        if width > dev.cols:
            return CompileResult("", _blank_grid(), clen, False,
                                 f"line exceeds {dev.cols} chars: {line!r}")

    grid = _blank_grid()
    for i, line in enumerate(lines):
        codes = charset.encode_text(line)
        if chips[i] is not None:
            codes = [chips[i]] + codes  # chip leads its line, centered alongside it
        row = dev.row_offset + i
        start = dev.col_offset + (dev.cols - len(codes)) // 2
        for j, code in enumerate(codes):
            grid[row][start + j] = code

    vbml_str = strip_hints(text) if not color_hints_enabled else text
    return CompileResult(vbml_str, grid, clen, True, "")


def _chip_rows(text: str, dev: DeviceSpec) -> list[int | None]:
    """Map a leading {color} on each wrapped line to a chip code. v1: first hint -> line 0."""
    plain = strip_hints(text)
    lines = _split_lines(plain, dev.cols)
    result: list[int | None] = [None] * len(lines)
    first = _HINT_RE.search(text)
    if first and lines:
        result[0] = COLOR_CODES[first.group(1)]
    return result


def content_region(grid: list[list[int]], dev: DeviceSpec | None = None) -> list[list[int]]:
    """Crop the full 6x22 board grid to the device's content area.

    `compile` centers the device's `lines x cols` content within the physical
    board; this extracts just that region so previews/history show exactly what
    the device displays (3x15 for a Note, the full 6x22 for a Vestaboard).
    """
    dev = dev or device.get(None)
    return [
        row[dev.col_offset:dev.col_offset + dev.cols]
        for row in grid[dev.row_offset:dev.row_offset + dev.lines]
    ]


def render_region(region: list[list[int]]) -> str:
    """ASCII view of a content region: '.' for blanks, glyphs otherwise.

    Reflects how the message looks on the board — uppercase letters/digits,
    a block (█) for color chips, dots for empty cells.
    """
    return "\n".join(
        "".join("." if c == BLANK else charset.code_to_char(c) for c in row)
        for row in region
    )


def truncate_to_fit(text: str, dev: DeviceSpec | None = None) -> str:
    """Word-boundary truncate to fit the device's lines/cols/content limit.

    Strips {color} hints; returns plain content only (last-resort path).
    """
    dev = dev or device.get(None)
    plain = strip_hints(text)
    words = plain.split()
    out_words: list[str] = []
    for w in words:
        if len(w) > dev.cols:
            break
        candidate = out_words + [w]
        joined = " ".join(candidate)
        if content_length(joined) > dev.content_limit:
            break
        if len(_split_lines(joined, dev.cols)) > dev.lines:
            break
        if any(len(line) > dev.cols for line in _split_lines(joined, dev.cols)):
            break
        out_words = candidate
    return " ".join(out_words)
