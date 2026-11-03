"""UI-thread-only, temporary dot hiding around the existing reset transaction.

The SDK thread must call run *before* taking the smooth lifecycle lock. The
manager pumps this queue before its normal backend poll can wait on that lock.
No nested Qt event loop, background repaint, or predicted wheel-state commit.
"""

from dataclasses import dataclass, field
from queue import Empty, SimpleQueue
from threading import Event, get_ident
from time import monotonic

from .area_target_helpers import area_key


def _target_signature(area):
    return tuple(area.get(key) for key in ('id', 'name', 'type', 'x', 'y', 'w', 'h'))


@dataclass(eq=False)
class _Request:
    key: object
    signature: tuple
    overlay: object
    requested_at: float = field(default_factory=monotonic)
    ready: Event = field(default_factory=Event)
    cancelled: Event = field(default_factory=Event)
    leased: bool = False


class WheelResetVisualFeedback:
    """Created and pumped by the manager's UI thread; run may be on the SDK thread."""

    def __init__(self, manager, *, qt=False, wait_seconds=0.10):
        self._manager = manager
        self._qt = bool(qt)
        self._wait_seconds = wait_seconds
        self._owner = get_ident()
        self._requests = SimpleQueue()
        # Only the UI owner reads/writes leases. Retain the overlay itself so
        # object identities cannot be recycled while a reset is outstanding.
        self._leases = {}

    def _record(self, stage, request, **extra):
        backend = getattr(self._manager, '_smooth_wheel_backend', None)
        record = getattr(backend, 'record_diagnostic', None)
        if callable(record):
            try:
                record('reset_visual', stage=stage, target=request.key,
                       elapsedMs=(monotonic() - request.requested_at) * 1000.0, **extra)
            except Exception:
                pass

    def _paint_hidden(self, overlay, hidden):
        overlay.set_wheel_dot_hidden(hidden)
        # update() only schedules a Qt paint. Complete this one widget's paint
        # before acknowledging; do not dispatch timers or re-enter controls.
        if self._qt:
            overlay.repaint()

    def _begin(self, request):
        if request.cancelled.is_set():
            return
        overlay = self._manager.overlays.get(request.key)
        if (overlay is not request.overlay
                or _target_signature(getattr(overlay, 'area', {})) != request.signature):
            self._record('target_changed', request)
            return
        key = id(overlay)
        lease = self._leases.get(key)
        if lease is None:
            lease = (overlay, bool(overlay.wheel_dot_hidden), set())
            self._leases[key] = lease
        lease[2].add(request)
        request.leased = True
        self._paint_hidden(overlay, True)
        self._record('hidden', request, originallyHidden=lease[1])

    def _end(self, request):
        # Cancellation suppresses a late begin, not restoration after a begin
        # already entered. No request mutex is held across widget painting.
        if not request.leased:
            return
        request.leased = False
        key = id(request.overlay)
        lease = self._leases.get(key)
        if lease is None:
            return
        lease[2].discard(request)
        if lease[2]:
            return
        del self._leases[key]
        overlay, original_hidden, _ = lease
        if self._manager.overlays.get(request.key) is overlay:
            # A reused widget may have new bounds; still release its hidden
            # flag. Never copy old geometry, call show(), or touch a replacement.
            self._paint_hidden(overlay, original_hidden)
            self._record('restored', request, hidden=original_hidden)

    def pump(self):
        if get_ident() != self._owner:
            return 0
        processed = 0
        while processed < 32:
            try:
                stage, request = self._requests.get_nowait()
            except Empty:
                break
            try:
                if stage == 'begin':
                    self._begin(request)
                else:
                    self._end(request)
            except Exception as exc:
                # A deleted/missing overlay must not prevent the real reset.
                self._record('ui_error', request, operation=stage, error=str(exc))
            finally:
                if stage == 'begin':
                    request.ready.set()
            processed += 1
        return processed

    def run(self, area, callback):
        if not area or area.get('type') != 'wheel':
            return callback()
        key = area_key(area)
        overlay = self._manager.overlays.get(key)
        if overlay is None:
            return callback()
        request = _Request(key, _target_signature(area), overlay)
        self._record('requested', request)
        self._requests.put(('begin', request))
        if get_ident() == self._owner:
            while not request.ready.is_set():
                self.pump()
        elif not request.ready.wait(self._wait_seconds):
            request.cancelled.set()
            self._record('timeout', request, waitMs=self._wait_seconds * 1000.0)
        try:
            return callback()
        finally:
            request.cancelled.set()
            self._requests.put(('end', request))
            if get_ident() == self._owner:
                self.pump()
