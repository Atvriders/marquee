from __future__ import annotations

import threading
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from marquee.models import Status


class Scheduler:
    def __init__(self, pipeline, reaper, store, config):
        self._pipeline = pipeline
        self._reaper = reaper
        self._store = store
        self._config = config
        self._tz = ZoneInfo(config.tz)
        self._sched = BackgroundScheduler(timezone=self._tz)
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        self._sched.add_job(
            self.trigger_refresh,
            CronTrigger.from_crontab(self._config.refresh_cron, timezone=self._tz),
            id="refresh",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._sched.add_job(
            self.trigger_reap,
            CronTrigger.from_crontab(self._config.reaper_cron, timezone=self._tz),
            id="reap",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._sched.start()

    def stop(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)

    def trigger_refresh(self) -> None:
        if not self._lock.acquire(blocking=False):
            self._store.log("warn", "skip", "refresh skipped: run already in progress")
            return
        try:
            self._running = True
            self._pipeline.run()
        finally:
            self._running = False
            self._lock.release()

    def trigger_reap(self) -> None:
        if not self._lock.acquire(blocking=False):
            self._store.log("warn", "skip", "reap skipped: run already in progress")
            return
        try:
            self._running = True
            movies = self._store.list_movies([Status.READY])
            for m in self._reaper.find_expired(movies):
                self._reaper.expire(m)
        finally:
            self._running = False
            self._lock.release()

    def status(self) -> dict:
        def nxt(job_id: str):
            job = self._sched.get_job(job_id) if self._sched.running else None
            return job.next_run_time.isoformat() if job and job.next_run_time else None

        return {
            "next_refresh": nxt("refresh"),
            "next_reap": nxt("reap"),
            "running": self._running,
        }
