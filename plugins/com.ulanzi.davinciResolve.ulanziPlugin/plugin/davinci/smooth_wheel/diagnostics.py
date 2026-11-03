"""Bounded diagnostic queue: pointer/tap paths never perform output I/O."""

from __future__ import annotations

from collections import deque
from threading import Event, Lock, Thread, current_thread
import time


class TraceBuffer:
    def __init__(self, emit, clock=time.monotonic, capacity=2048, history=128):
        self._emit = emit
        self._clock = clock
        self._capacity = capacity
        self._pending = deque()
        self._recent = deque(maxlen=history)
        self._lock = Lock()
        self._stop = Event()
        self._thread = None
        self._sequence = 0
        self._dropped = 0
        self._failed_batches = 0

    def start(self):
        if self._thread is None:
            self._thread = Thread(target=self._run, name="wheel-diagnostics", daemon=True)
            self._thread.start()

    def record(self, event):
        item = {"monotonic": self._clock(), "wallTimeMs": time.time() * 1000.0, **event}
        with self._lock:
            self._sequence += 1
            item["seq"] = self._sequence
            if len(self._pending) >= self._capacity:
                self._pending.popleft()
                self._dropped += 1
            self._pending.append(item)
            self._recent.append(item)

    def recent(self, session_id):
        with self._lock:
            return [dict(item) for item in self._recent if item.get("sessionId") == session_id]

    def statistics(self):
        with self._lock:
            return {"sequence": self._sequence, "queuedEvents": len(self._pending),
                    "droppedEvents": self._dropped, "failedBatches": self._failed_batches}

    def flush(self):
        with self._lock:
            events = list(self._pending)
            self._pending.clear()
            dropped = self._dropped
        if events:
            try:
                self._emit({"type": "telemetry", "events": events, "droppedEvents": dropped})
            except Exception:
                with self._lock:
                    self._failed_batches += 1
                    self._dropped += len(events)

    def close(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            # A blocked diagnostic pipe must never hold up emergency release.
            thread.join(0.25)

    def _run(self):
        while not self._stop.wait(0.1):
            self.flush()
        self.flush()
