"""Cooperative layout discovery cancellation; never lock the gesture runner."""

import threading
import time


class LayoutScanSuperseded(RuntimeError):
    """A scheduled scan lost priority to live wheel input."""


def note_layout_input(manager):
    # Mark before recognition/try_submit, without changing its motion clock,
    # hover ownership or the existing successful-input bookkeeping.
    manager._layout_input_epoch = getattr(manager, '_layout_input_epoch', 0) + 1
    manager._last_layout_input_at = time.time()


def smooth_layout_busy(manager):
    backend = getattr(manager, '_smooth_wheel_backend', None)
    # ``armed`` survives idle UP indefinitely. Blocking on is_active alone
    # would prevent discovery of keyboard-only layout changes forever. Read
    # the backend's existing callback-owned boolean (no native I/O or session
    # snapshot); recent/just-admitted input is protected separately by epoch
    # and the quiet interval, including the double-click-guard wait.
    return (
        backend is not None
        and backend.is_active()
        and bool(getattr(backend, '_pointer_down', True))
    )


def check_layout_scan(owner):
    checkpoint = getattr(owner, '_layout_scan_checkpoint', None)
    if checkpoint is not None:
        checkpoint()


def make_layout_scan_checkpoint(manager, quiet_seconds):
    epoch = getattr(manager, '_layout_input_epoch', 0)
    owner_thread = threading.get_ident()

    def checkpoint():
        # LabelFinder is also read by the input thread. Only the discovery
        # caller may be interrupted, never a live preflight/target check.
        if threading.get_ident() != owner_thread:
            return
        last_input = getattr(manager, '_last_layout_input_at', 0.0)
        if (
            not manager.is_monitoring
            or getattr(manager, '_layout_input_epoch', 0) != epoch
            or (last_input and time.time() - last_input < quiet_seconds)
            or smooth_layout_busy(manager)
        ):
            raise LayoutScanSuperseded('wheel_input_priority')

    return checkpoint
