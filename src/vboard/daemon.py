import hashlib
import logging
import os
import time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from vboard import config, history, logging_setup, pipeline

log = logging_setup.get_logger("vboard.daemon")


def cron_to_trigger(cron: str) -> CronTrigger:
    minute, hour, dom, month, dow = cron.split()
    return CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow)


class Daemon:
    def __init__(self, config_path: Path, scheduler=None, runner=pipeline.run_once) -> None:
        self.config_path = Path(config_path)
        self.scheduler = scheduler or BackgroundScheduler()
        self.runner = runner
        self._last_signature: str | None = None

    def _signature(self) -> str | None:
        # Hash the file contents rather than trusting st_mtime: filesystem mtime
        # granularity (1s on some mounts) can hide an edit made in the same tick
        # as the previous sync, which would otherwise be missed permanently.
        try:
            data = self.config_path.read_bytes()
        except FileNotFoundError:
            return None
        return hashlib.sha256(data).hexdigest()

    def sync_jobs(self) -> None:
        cfg = config.load_config(self.config_path)
        config.register_config_secrets(cfg)
        self.scheduler.remove_all_jobs()
        for prompt in cfg.prompts:
            if not prompt.enabled:
                continue
            self.scheduler.add_job(
                self._fire, trigger=cron_to_trigger(prompt.cron),
                args=[prompt.id], id=prompt.id,
            )
        self._last_signature = self._signature()
        log.info("synced %d job(s)", len(self.scheduler.get_jobs()))

    def maybe_reload(self) -> bool:
        current = self._signature()
        if current != self._last_signature:
            self.sync_jobs()
            return True
        return False

    def _fire(self, prompt_id: str) -> None:
        cfg = config.load_config(self.config_path)
        prompt = next((p for p in cfg.prompts if p.id == prompt_id), None)
        if prompt is None:
            log.warning("prompt id=%s no longer exists", prompt_id)
            return
        result = self.runner(cfg, prompt)
        # The runner swallows its own errors and returns a result; if we don't
        # inspect it, delivery failures are completely invisible (APScheduler
        # still reports "executed successfully" because _fire didn't raise).
        if result is not None and not result.delivered:
            log.error("delivery failed for prompt id=%s attempts=%d: %s",
                      prompt_id, result.attempts, result.error)
        elif result is not None and result.delivered:
            self._record_history(prompt, result)

    def _record_history(self, prompt: config.PromptEntry, result) -> None:
        # Never let a history-write failure break the scheduled run: the message
        # was already delivered to the board by this point.
        try:
            history.append(
                history.history_path_for(self.config_path),
                history.HistoryEntry(
                    timestamp=history.now_iso(),
                    prompt_id=prompt.id,
                    prompt_title=prompt.display_title,
                    text=result.text,
                    truncated=result.truncated,
                    grid=result.grid,
                    device=result.device,
                ),
            )
        except Exception as e:  # noqa: BLE001 - best-effort logging only
            log.warning("could not record history for prompt id=%s: %s", prompt.id, e)

    def start(self) -> None:
        self.sync_jobs()
        self.scheduler.start()

    def run_forever(self, poll_interval: float = 5.0) -> None:
        self.start()
        try:
            while True:
                time.sleep(poll_interval)
                self.maybe_reload()
        except (KeyboardInterrupt, SystemExit):
            self.scheduler.shutdown()


def main() -> None:
    logging_setup.configure_logging(logging.INFO)
    path = Path(os.environ.get("VBOARD_CONFIG", "config.json"))
    Daemon(path).run_forever()


if __name__ == "__main__":
    main()
