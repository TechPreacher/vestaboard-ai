import logging
import os
import time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from vboard import config, logging_setup, pipeline

log = logging_setup.get_logger("vboard.daemon")


def cron_to_trigger(cron: str) -> CronTrigger:
    minute, hour, dom, month, dow = cron.split()
    return CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow)


class Daemon:
    def __init__(self, config_path: Path, scheduler=None, runner=pipeline.run_once) -> None:
        self.config_path = Path(config_path)
        self.scheduler = scheduler or BackgroundScheduler()
        self.runner = runner
        self._last_mtime: float | None = None

    def _mtime(self) -> float | None:
        try:
            return os.stat(self.config_path).st_mtime
        except FileNotFoundError:
            return None

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
        self._last_mtime = self._mtime()
        log.info("synced %d job(s)", len(self.scheduler.get_jobs()))

    def maybe_reload(self) -> bool:
        current = self._mtime()
        if current != self._last_mtime:
            self.sync_jobs()
            return True
        return False

    def _fire(self, prompt_id: str) -> None:
        cfg = config.load_config(self.config_path)
        prompt = next((p for p in cfg.prompts if p.id == prompt_id), None)
        if prompt is None:
            log.warning("prompt id=%s no longer exists", prompt_id)
            return
        self.runner(cfg, prompt)

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
