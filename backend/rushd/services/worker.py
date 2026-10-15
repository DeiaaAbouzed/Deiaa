"""Background reading queue: interactive reads jump ahead of bulk feeding."""

from __future__ import annotations

import itertools
import logging
import queue
import threading

from sqlalchemy import select

from ..models import Prescription
from .reader import Reader

log = logging.getLogger("rushd.worker")

PRIORITY_INTERACTIVE = 0
PRIORITY_BULK = 10
RETRY_DELAYS = (15.0, 60.0, 180.0)


class Worker:
    def __init__(self, ctx, threads: int):
        self.ctx = ctx
        self.reader = Reader(ctx)
        self.threads = threads
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._timers: list[threading.Timer] = []

    def start(self) -> None:
        with self.ctx.sf() as db:
            rows = (
                db.execute(
                    select(Prescription)
                    .where(Prescription.status.in_(("queued", "processing")))
                    .order_by(Prescription.priority, Prescription.id)
                )
                .scalars()
                .all()
            )
            for rx in rows:
                rx.status = "queued"  # a crash mid-read leaves "processing" behind
            db.commit()
            pending = [(rx.priority, rx.id) for rx in rows]
        for priority, rx_id in pending:
            self._queue.put((priority, next(self._seq), rx_id))
        for i in range(self.threads):
            t = threading.Thread(target=self._loop, name=f"rushd-reader-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        if pending:
            log.info("resumed %d queued prescriptions", len(pending))

    def submit(self, rx_id: int, priority: int = PRIORITY_INTERACTIVE) -> None:
        if self.threads == 0:  # synchronous mode (tests, single-shot CLI): retry immediately
            while self.reader.process(rx_id):
                pass
            return
        self._queue.put((priority, next(self._seq), rx_id))

    def pending(self) -> int:
        return self._queue.qsize()

    def stop(self) -> None:
        self._stop.set()
        for timer in self._timers:
            timer.cancel()
        for t in self._threads:
            t.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                priority, _, rx_id = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                if self.reader.process(rx_id):
                    attempt = self.reader.attempts.get(rx_id, 1)
                    delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                    timer = threading.Timer(delay, self._queue.put, args=((priority, next(self._seq), rx_id),))
                    timer.daemon = True
                    timer.start()
                    self._timers = [t for t in self._timers if t.is_alive()] + [timer]
            except Exception:  # pragma: no cover - Reader already handles its own errors
                log.exception("worker crashed on prescription %s", rx_id)
            finally:
                self._queue.task_done()
