from pathlib import Path

from vboard import device, history, vbml

NOTE = device.DEVICES["note"]


def _entry(text: str, **kw) -> history.HistoryEntry:
    grid = vbml.content_region(vbml.compile(text, color_hints_enabled=False).grid, NOTE)
    defaults = dict(
        timestamp="2026-06-29T08:00:00+02:00",
        prompt_id="a",
        prompt_title="Weather",
        text=text,
        truncated=False,
        grid=grid,
        device="note",
    )
    defaults.update(kw)
    return history.HistoryEntry(**defaults)


def test_history_path_is_beside_config(tmp_path: Path):
    cfg = tmp_path / "sub" / "config.json"
    assert history.history_path_for(cfg) == tmp_path / "sub" / "history.json"


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert history.load(tmp_path / "history.json") == []


def test_append_then_load_roundtrips(tmp_path: Path):
    path = tmp_path / "history.json"
    history.append(path, _entry("RAIN TODAY"))
    history.append(path, _entry("SUNNY", prompt_id="b"))
    loaded = history.load(path)
    assert [e.text for e in loaded] == ["RAIN TODAY", "SUNNY"]
    assert loaded[1].prompt_id == "b"


def test_append_creates_parent_dir(tmp_path: Path):
    path = tmp_path / "data" / "history.json"
    history.append(path, _entry("HI"))
    assert path.exists()


def test_append_caps_entries(tmp_path: Path):
    path = tmp_path / "history.json"
    for i in range(5):
        history.append(path, _entry(f"MSG {i}"), max_entries=3)
    loaded = history.load(path)
    assert len(loaded) == 3
    assert [e.text for e in loaded] == ["MSG 2", "MSG 3", "MSG 4"]


def test_corrupt_file_loads_as_empty(tmp_path: Path):
    path = tmp_path / "history.json"
    path.write_text("not json", encoding="utf-8")
    assert history.load(path) == []


def test_legacy_entry_without_device_defaults_to_note(tmp_path: Path):
    # Entries written before the device field existed must still load.
    path = tmp_path / "history.json"
    path.write_text(
        '[{"timestamp": "2026-06-29T08:00:00+02:00", "prompt_id": "a", '
        '"prompt_title": "T", "text": "HI", "truncated": false, '
        '"grid": [[0]]}]',
        encoding="utf-8",
    )
    loaded = history.load(path)
    assert len(loaded) == 1
    assert loaded[0].device == "note"
