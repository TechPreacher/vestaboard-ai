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
    "!": 37,
    "@": 38,
    "#": 39,
    "$": 40,
    "(": 41,
    ")": 42,
    "-": 44,
    "+": 46,
    "&": 47,
    "=": 48,
    ";": 49,
    ":": 50,
    "'": 52,
    '"': 53,
    "%": 54,
    ",": 55,
    ".": 56,
    "/": 59,
    "?": 60,
    "°": 62,
}
_BASE.update(_PUNCT)

COLOR_CODES: dict[str, int] = {
    "red": 63,
    "orange": 64,
    "yellow": 65,
    "green": 66,
    "blue": 67,
    "violet": 68,
    "white": 69,
    "black": 70,
    "filled": 71,
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


# Reverse map for rendering a grid back to readable text. Letters/digits/punct
# decode to their glyph; color chips have no glyph, so they render as a block.
_CODE_TO_CHAR: dict[int, str] = {code: ch for ch, code in _BASE.items()}
for _code in COLOR_CODES.values():
    _CODE_TO_CHAR[_code] = "█"


def code_to_char(code: int) -> str:
    """Decode a character code to its glyph. BLANK and unknown codes -> ' '."""
    return _CODE_TO_CHAR.get(code, " ")
