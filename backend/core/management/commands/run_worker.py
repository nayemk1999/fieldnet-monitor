"""Production background loop: runs due work every few seconds.

In TEST_MODE background work must only run inside /test/clock and /test/drain,
so this command idles instead of exiting (keeps docker compose quiet).
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from core import clock, config, jobs


class Command(BaseCommand):
    def handle(self, *args, **options):
        if settings.TEST_MODE:
            self.stdout.write("TEST_MODE=1: worker idle; use /test/clock or /test/drain")
            while True:
                time.sleep(3600)
        self.stdout.write(f"worker started, polling every {config.WORKER_POLL_SECONDS}s")
        while True:
            try:
                jobs.run_due(clock.now())
            except Exception as e:  # keep the loop alive; the next tick retries
                self.stderr.write(f"run_due failed: {e!r}")
            time.sleep(config.WORKER_POLL_SECONDS)
