"""Bounded, best-effort host diagnostics with no serialization on motion threads.

``record`` transfers ownership of an event dictionary to the writer: callers
must not mutate it or its nested payload after enqueueing. Existing telemetry
batches are serialized as supplied, without copying or wrapping their contents.
This writer never rotates, truncates, or deletes earlier trace files.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, current_thread
import time
import uuid


DEFAULT_MAX_BYTES = 128 * 1024 * 1024
DEFAULT_QUEUE_CAPACITY = 256
_TERMINAL_RESERVE_BYTES = 512
_POLL_SECONDS = 0.025


def _default_directory():
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return (root / "Ulanzi" / "UlanziDeck" / "logs"
                / "com.ulanzi.ulanzistudio.davinciResolve" / "wheel-trace")
    return (
        Path.home() / "Library" / "Application Support" / "Ulanzi"
        / "UlanziDeck" / "logs" / "com.ulanzi.ulanzistudio.davinciResolve"
        / "wheel-trace"
    )


class HostWheelTrace:
    """One uniquely named NDJSON trace, written by a bounded daemon queue.

    ``ready`` is set only after exclusive file creation succeeds; ``finished``
    is set after the worker finishes, including open/write failures. ``written``
    counts telemetry records, not the terminal budget marker. Errors and all
    rejected/discarded records remain visible through ``status``.
    """

    def __init__(self, directory=None, *, queue_capacity=DEFAULT_QUEUE_CAPACITY,
                 max_bytes=DEFAULT_MAX_BYTES):
        queue_capacity = int(queue_capacity)
        max_bytes = int(max_bytes)
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be positive")
        if max_bytes < _TERMINAL_RESERVE_BYTES:
            raise ValueError("max_bytes must be at least 512")
        self._directory = Path(directory) if directory is not None else _default_directory()
        filename = "wheel-%s-%s-%s.ndjson" % (
            os.getpid(), time.time_ns(), uuid.uuid4().hex[:12],
        )
        self._path = self._directory / filename
        self._max_bytes = max_bytes
        self._queue = Queue(maxsize=queue_capacity)
        # This lock protects only short bookkeeping/admission operations. It is
        # never held around JSON, file operations, callbacks, or thread joins.
        self._lock = Lock()
        self._stop_requested = Event()
        self.ready = Event()
        self.finished = Event()
        self._accepting = True
        self._enqueued = 0
        self._dropped = 0
        self._written = 0
        self._bytes_written = 0
        self._error = None
        self._serialization_errors = 0
        self._write_errors = 0
        self._invalid_events = 0
        self._budget_exhausted = False
        self._terminal_written = False
        self._thread = Thread(target=self._run, name="wheel-host-trace", daemon=True)
        try:
            self._thread.start()
        except Exception as exc:
            self._accepting = False
            self._error = "start: %s: %s" % (type(exc).__name__, exc)
            self.finished.set()

    def record(self, event):
        """Attempt immediate admission; never JSON-encode, copy, or write here."""
        with self._lock:
            if not isinstance(event, dict):
                self._invalid_events += 1
                self._dropped += 1
                return False
            if not self._accepting:
                self._dropped += 1
                return False
            try:
                self._queue.put_nowait(event)
            except Full:
                self._dropped += 1
                return False
            self._enqueued += 1
            return True

    def status(self):
        with self._lock:
            return {
                "path": str(self._path),
                "ready": self.ready.is_set(),
                "accepting": self._accepting,
                "finished": self.finished.is_set(),
                "enqueued": self._enqueued,
                "queued": self._queue.qsize(),
                "queue_capacity": self._queue.maxsize,
                "dropped": self._dropped,
                "written": self._written,
                "error": self._error,
                "invalid_events": self._invalid_events,
                "serialization_errors": self._serialization_errors,
                "write_errors": self._write_errors,
                "bytes_written": self._bytes_written,
                "budget": {
                    "max_bytes": self._max_bytes,
                    "remaining_bytes": max(0, self._max_bytes - self._bytes_written),
                    "exhausted": self._budget_exhausted,
                    "terminal_written": self._terminal_written,
                },
            }

    def close(self, timeout=0.25):
        """Stop admission and boundedly wait; a slow daemon may finish later."""
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            timeout = 0.25
        if not math.isfinite(timeout):
            timeout = 0.25
        timeout = max(0.0, min(timeout, 1.0))
        with self._lock:
            self._accepting = False
            self._stop_requested.set()
        if self._thread.ident is not None and self._thread is not current_thread():
            self._thread.join(timeout=timeout)
        return self.status()

    def _discard_queued(self):
        discarded = 0
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                break
            else:
                discarded += 1
        with self._lock:
            self._dropped += discarded

    @staticmethod
    def _encode(event):
        return (json.dumps(event, ensure_ascii=False, allow_nan=False,
                           separators=(",", ":")) + "\n").encode("utf-8")

    def _write(self, stream, payload, *, terminal=False):
        count = stream.write(payload)
        if count != len(payload):
            raise OSError("short trace write: %s of %s bytes" % (count, len(payload)))
        stream.flush()
        with self._lock:
            self._bytes_written += count
            if terminal:
                self._terminal_written = True
            else:
                self._written += 1

    def _finish_budget(self, stream):
        with self._lock:
            self._budget_exhausted = True
            self._accepting = False
            self._dropped += 1  # The current event which would exceed the cap.
        self._discard_queued()
        with self._lock:
            terminal = {
                "type": "host_trace_budget_exhausted",
                "max_bytes": self._max_bytes,
                "bytes_before_terminal": self._bytes_written,
                "written": self._written,
                "dropped_at_terminal": self._dropped,
            }
        payload = self._encode(terminal)
        if len(payload) > _TERMINAL_RESERVE_BYTES:
            payload = self._encode({"type": "host_trace_budget_exhausted"})
        self._write(stream, payload, terminal=True)

    def _run(self):
        stream = None
        current_event = False
        phase = "open"
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            # Exclusive creation protects existing traces even in an unlikely
            # identifier collision. Opening/mkdir happen only on this worker.
            stream = self._path.open("xb")
            self.ready.set()
            phase = "write"
            while True:
                if self._stop_requested.is_set() and self._queue.empty():
                    break
                try:
                    event = self._queue.get(timeout=_POLL_SECONDS)
                except Empty:
                    continue
                current_event = True
                try:
                    payload = self._encode(event)
                except Exception as exc:
                    with self._lock:
                        self._serialization_errors += 1
                        self._dropped += 1
                        self._error = "serialize: %s: %s" % (type(exc).__name__, exc)
                    current_event = False
                    continue
                if self._bytes_written + len(payload) > (
                        self._max_bytes - _TERMINAL_RESERVE_BYTES):
                    current_event = False  # Budget handler counts this record.
                    self._finish_budget(stream)
                    break
                self._write(stream, payload)
                current_event = False
        except Exception as exc:
            with self._lock:
                self._accepting = False
                self._error = "%s: %s: %s" % (phase, type(exc).__name__, exc)
                self._write_errors += int(phase == "write")
                self._dropped += int(current_event)
            self._discard_queued()
        finally:
            with self._lock:
                self._accepting = False
            if stream is not None:
                try:
                    stream.close()
                except Exception as exc:
                    with self._lock:
                        self._write_errors += 1
                        self._error = "close: %s: %s" % (type(exc).__name__, exc)
            self.finished.set()


__all__ = ["HostWheelTrace", "DEFAULT_MAX_BYTES", "DEFAULT_QUEUE_CAPACITY"]
