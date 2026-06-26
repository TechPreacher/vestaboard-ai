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
