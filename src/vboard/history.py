import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from vboard import logging_setup

log = logging_setup.get_logger("vboard.history")

# Keep the persisted log bounded so it can't grow without limit on a long-running
# board. Oldest entries are dropped first.
MAX_ENTRIES = 500


class HistoryEntry(BaseModel):
    timestamp: str  # ISO 8601, local timezone
    prompt_id: str
    prompt_title: str
    text: str
    truncated: bool
    grid: list[list[int]]  # the device's content region (character codes)
    # Device the message was generated for. Defaults to "note" so history files
    # written before this field existed still load.
    device: str = "note"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def history_path_for(config_path: Path) -> Path:
    """History lives alongside the config file (same /data volume in containers)."""
    return Path(config_path).parent / "history.json"


def load(path: Path) -> list[HistoryEntry]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        return [HistoryEntry.model_validate(e) for e in json.loads(raw)]
    except (ValueError, OSError) as e:
        log.warning("could not read history at %s: %s", path, e)
        return []


def _atomic_write(path: Path, entries: list[HistoryEntry]) -> None:
    data = json.dumps([e.model_dump() for e in entries], indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".history.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append(path: Path, entry: HistoryEntry, *, max_entries: int = MAX_ENTRIES) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = load(path)
    entries.append(entry)
    if len(entries) > max_entries:
        entries = entries[-max_entries:]
    _atomic_write(path, entries)
