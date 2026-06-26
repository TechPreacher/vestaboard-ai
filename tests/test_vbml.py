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
