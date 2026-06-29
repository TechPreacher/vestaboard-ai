from vboard import device, vbml

NOTE = device.DEVICES["note"]
BOARD = device.DEVICES["vestaboard"]


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


def test_color_chip_is_inside_note_region():
    # The chip must land within the 3x15 Note so preview/history reflect it.
    r = vbml.compile("{red}HI", color_hints_enabled=True)
    region = vbml.content_region(r.grid, NOTE)
    flat = [c for row in region for c in row]
    assert vbml.COLOR_RED in flat
    assert "█" in vbml.render_region(region)


def test_chip_counts_toward_line_width():
    # 15 text chars + a chip cell = 16 > 15, so it must not validate.
    r = vbml.compile("{red}ABCDEFGHIJKLMNO", color_hints_enabled=True)
    assert r.valid is False
    assert "15" in r.reason
    # Same line without the chip fits exactly.
    assert vbml.compile("ABCDEFGHIJKLMNO", color_hints_enabled=False).valid is True
    # 14 text chars + chip fits.
    assert vbml.compile("{red}ABCDEFGHIJKLMN", color_hints_enabled=True).valid is True


def test_color_hints_disabled_strips_tokens_no_chip():
    r = vbml.compile("{red}HI", color_hints_enabled=False)
    flat = [c for row in r.grid for c in row]
    assert vbml.COLOR_RED not in flat


def test_compile_single_long_word_is_invalid():
    r = vbml.compile("ABCDEFGHIJKLMNOP", color_hints_enabled=False)  # 16 chars, one word
    assert r.valid is False
    assert "15" in r.reason


def test_truncate_drops_unrenderable_long_word():
    # a 20-char single word cannot be placed; truncate must yield compile-valid output
    out = vbml.truncate_to_fit("ABCDEFGHIJKLMNOPQRST and more text here")
    assert vbml.compile(out, color_hints_enabled=False).valid is True


def test_truncate_output_always_compiles_valid():
    text = "ALPHA BRAVO CHARLIE DELTA ECHO FOXTROT GOLF HOTEL INDIA JULIET KILO"
    out = vbml.truncate_to_fit(text)
    assert vbml.compile(out, color_hints_enabled=False).valid is True


def test_note_region_is_three_by_fifteen():
    grid = vbml.compile("RAIN TODAY", color_hints_enabled=False).grid
    region = vbml.content_region(grid, NOTE)
    assert len(region) == NOTE.lines
    assert all(len(row) == NOTE.cols for row in region)


def test_render_region_uses_dots_and_uppercase():
    region = vbml.content_region(vbml.compile("HI", color_hints_enabled=False).grid, NOTE)
    rendered = vbml.render_region(region)
    lines = rendered.split("\n")
    assert len(lines) == 3
    assert all(len(line) == NOTE.cols for line in lines)
    assert "HI" in "".join(lines)
    assert "." in rendered  # blank cells render as dots


def test_vestaboard_device_uses_full_board():
    # Full board: 6 lines x 22 cols, no centering offset, 132-char limit.
    assert BOARD.content_limit == 132
    region = vbml.content_region(vbml.compile("HELLO", False, BOARD).grid, BOARD)
    assert len(region) == 6
    assert all(len(row) == 22 for row in region)


def test_vestaboard_allows_more_than_note():
    # A message that overflows a Note fits comfortably on a full Vestaboard.
    text = " ".join(["WORD"] * 12)  # 60 content chars across many lines
    assert vbml.compile(text, False, NOTE).valid is False
    assert vbml.compile(text, False, BOARD).valid is True


def test_vestaboard_line_can_be_22_chars():
    line = "A" * 22
    assert vbml.compile(line, False, BOARD).valid is True
    assert vbml.compile("A" * 23, False, BOARD).valid is False
