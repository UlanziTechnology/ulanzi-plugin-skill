"""Render-frame-paced dial event scheduler for smooth timeline control."""

import threading
import time


class TimelineEventScheduler:
    """Coalesce dial ticks while bounding latency and stale motion."""

    def __init__(
        self,
        execute_fn,
        result_fn=None,
        frame_interval_seconds=1.0 / 60.0,
        stale_after_seconds=0.095,
        max_batch_ticks=8,
        max_pending_ticks=48,
        batch_limit_fn=None,
    ):
        self.execute_fn = execute_fn
        self.result_fn = result_fn or (lambda _ok, _mode, _ticks: None)
        self.frame_interval_seconds = float(frame_interval_seconds)
        self.stale_after_seconds = float(stale_after_seconds)
        self.max_batch_ticks = max(1, int(max_batch_ticks))
        self.max_pending_ticks = max(self.max_batch_ticks, int(max_pending_ticks))
        self.batch_limit_fn = batch_limit_fn

        self._condition = threading.Condition()
        self._pending_mode = None
        self._pending_ticks = 0
        self._last_input_at = 0.0
        self._last_dispatch_at = 0.0
        self._generation = 0
        self._stopped = False
        self._thread = None

    def submit(self, mode, ticks):
        ticks = int(ticks)
        if not ticks:
            return False
        now = time.monotonic()
        with self._condition:
            if self._stopped:
                return False
            if self._pending_mode != mode:
                self._pending_ticks = 0
                self._pending_mode = mode
                self._generation += 1
            elif self._pending_ticks and (self._pending_ticks > 0) != (ticks > 0):
                # A direction reversal is a brake: old queued movement must never
                # leak through after the user has turned the other way.
                self._pending_ticks = 0
                self._generation += 1

            self._pending_ticks += ticks
            self._pending_ticks = max(
                -self.max_pending_ticks,
                min(self.max_pending_ticks, self._pending_ticks),
            )
            self._last_input_at = now
            self._ensure_worker_locked()
            self._condition.notify_all()
        return True

    def flush(self):
        with self._condition:
            self._pending_ticks = 0
            self._pending_mode = None
            self._generation += 1
            self._condition.notify_all()

    def stop(self):
        with self._condition:
            self._stopped = True
            self._pending_ticks = 0
            self._pending_mode = None
            self._generation += 1
            self._condition.notify_all()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.35)

    def pending_snapshot(self):
        with self._condition:
            return self._pending_mode, self._pending_ticks, self._generation

    def _ensure_worker_locked(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="davinci-timeline-dial",
            daemon=True,
        )
        self._thread.start()

    def _worker_loop(self):
        while True:
            with self._condition:
                while not self._stopped and not self._pending_ticks:
                    self._condition.wait()
                if self._stopped:
                    return

                now = time.monotonic()
                if now - self._last_input_at > self.stale_after_seconds:
                    self._pending_ticks = 0
                    self._pending_mode = None
                    self._generation += 1
                    continue

                wait_seconds = self.frame_interval_seconds - (now - self._last_dispatch_at)
                if wait_seconds > 0:
                    self._condition.wait(timeout=wait_seconds)
                    continue

                mode = self._pending_mode
                batch_limit = self.max_batch_ticks
                if self.batch_limit_fn:
                    try:
                        batch_limit = min(batch_limit, max(1, int(self.batch_limit_fn(mode))))
                    except Exception:
                        batch_limit = self.max_batch_ticks
                sign = 1 if self._pending_ticks > 0 else -1
                batch = sign * min(abs(self._pending_ticks), batch_limit)
                generation = self._generation
                self._pending_ticks -= batch
                if not self._pending_ticks:
                    self._pending_mode = None
                self._last_dispatch_at = now

            ok = False
            try:
                ok = bool(self.execute_fn(mode, batch))
            except Exception:
                ok = False

            try:
                self.result_fn(ok, mode, batch)
            except Exception:
                pass

            if not ok:
                with self._condition:
                    # Focus loss or backend failure discards the tail instead of
                    # replaying it later as an unexpected jump.
                    if generation == self._generation:
                        self._pending_ticks = 0
                        self._pending_mode = None
                        self._generation += 1


__all__ = ["TimelineEventScheduler"]
