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
