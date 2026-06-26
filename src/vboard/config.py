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
