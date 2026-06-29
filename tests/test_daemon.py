from pathlib import Path

from vboard import daemon, history
from vboard.config import AppConfig, PromptEntry, save_config
from vboard.pipeline import PipelineResult


def _write(path: Path, prompts):
    save_config(AppConfig(prompts=prompts), path)


def test_cron_to_trigger_parses_five_fields():
    trig = daemon.cron_to_trigger("0 8 * * *")
    # APScheduler CronTrigger stringifies fields; hour=8 present
    assert "hour='8'" in str(trig)


def test_sync_jobs_adds_one_job_per_enabled_prompt(tmp_path: Path):
    path = tmp_path / "config.json"
    _write(path, [
        PromptEntry(id="a", text="x", cron="0 8 * * *", enabled=True),
        PromptEntry(id="b", text="y", cron="0 9 * * *", enabled=False),
    ])
    d = daemon.Daemon(path)
    d.sync_jobs()
    assert len(d.scheduler.get_jobs()) == 1


def test_maybe_reload_detects_change(tmp_path: Path):
    path = tmp_path / "config.json"
    _write(path, [PromptEntry(id="a", text="x", cron="0 8 * * *")])
    d = daemon.Daemon(path)
    d.sync_jobs()
    assert d.maybe_reload() is False  # no change yet
    _write(path, [
        PromptEntry(id="a", text="x", cron="0 8 * * *"),
        PromptEntry(id="c", text="z", cron="0 10 * * *"),
    ])
    assert d.maybe_reload() is True
    assert len(d.scheduler.get_jobs()) == 2


def test_fire_invokes_runner_with_prompt(tmp_path: Path):
    path = tmp_path / "config.json"
    _write(path, [PromptEntry(id="a", text="hello", cron="0 8 * * *")])
    seen = {}
    d = daemon.Daemon(path, runner=lambda cfg, prompt: seen.update(id=prompt.id, text=prompt.text))
    d.sync_jobs()
    d._fire("a")
    assert seen == {"id": "a", "text": "hello"}


def test_fire_records_history_on_delivery(tmp_path: Path):
    path = tmp_path / "config.json"
    _write(path, [PromptEntry(id="a", text="hello", title="Greeting", cron="0 8 * * *")])
    grid = [[0] * 15 for _ in range(3)]
    delivered = PipelineResult(True, "HELLO", False, 1, "", grid, "note")
    d = daemon.Daemon(path, runner=lambda cfg, prompt: delivered)
    d.sync_jobs()
    d._fire("a")
    entries = history.load(history.history_path_for(path))
    assert len(entries) == 1
    assert entries[0].prompt_title == "Greeting"
    assert entries[0].text == "HELLO"
    assert entries[0].grid == grid
    assert entries[0].device == "note"


def test_fire_does_not_record_history_on_failure(tmp_path: Path):
    path = tmp_path / "config.json"
    _write(path, [PromptEntry(id="a", text="hello", cron="0 8 * * *")])
    failed = PipelineResult(False, "txt", False, 3, "boom")
    d = daemon.Daemon(path, runner=lambda cfg, prompt: failed)
    d.sync_jobs()
    d._fire("a")
    assert history.load(history.history_path_for(path)) == []


def test_fire_logs_when_delivery_fails(tmp_path: Path, caplog):
    import logging

    path = tmp_path / "config.json"
    _write(path, [PromptEntry(id="a", text="hello", cron="0 8 * * *")])
    failed = PipelineResult(False, "txt", False, 3, "llm error: read timed out")
    d = daemon.Daemon(path, runner=lambda cfg, prompt: failed)
    d.sync_jobs()
    with caplog.at_level(logging.ERROR):
        d._fire("a")
    assert any("delivery failed" in r.message or "delivery failed" in r.getMessage()
               for r in caplog.records)
