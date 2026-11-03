# Copyright (c) Ulanzi DaVinci Resolve plugin contributors.
# Migrated from this project's validated gesture lab (tourbox-wheel-lab/src/tourbox_wheel_lab/sinks.py, v0.1.20).
# This is first-party experimental code promoted into the formal candidate;
# keep host-specific pointer and recognition policy outside this pure core.

"""Output sinks for the isolated gesture research engine.

Only a recording sink is provided here on purpose.  The lab must be safe to run
without moving the user's real pointer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import List, Optional, Protocol

from .geometry import Vec2


class PointerEventKind(str, Enum):
    """Pointer lifecycle events emitted by :class:`GestureEngine`."""

    DOWN = "DOWN"
    DRAG = "DRAG"
    UP = "UP"


@dataclass(frozen=True)
class MotionFrame:
    """Logical wheel motion consumed during one scheduler frame.

    A motion-aware host sink receives both ends of the logical step, so it can
    preserve an exact absolute handle path and attach error-diffused integer
    delta diagnostics. ``logical_applied`` is expressed in degrees for
    ``orbit`` and pixels for ``push_pull``.
    """

    mode: str
    logical_before: Vec2
    logical_after: Vec2
    logical_applied: float
    timestamp: float
    clamped: bool = False
    crossed_center: bool = False
    purpose: str = "user_input"


@dataclass(frozen=True)
class TransportStep:
    """Result of servicing a sink-owned multi-phase pointer transport.

    A transport-aware sink can temporarily hold normal logical frames while
    it advances a host protocol such as an edge rebase. ``handled`` remains
    true for the call which completes the final phase, preventing that same
    scheduler turn from also emitting ordinary wheel motion.
    """

    handled: bool
    phase: str = ""
    next_wakeup_at: Optional[float] = None
    cancelled: bool = False
    completed: bool = False


@dataclass(frozen=True)
class PointerEvent:
    """One immutable, timestamped pointer event."""

    kind: PointerEventKind
    position: Vec2
    timestamp: float
    reason: str = ""
    motion: Optional[MotionFrame] = None


class GestureSink(Protocol):
    """Minimal target used by the gesture engine."""

    def down(self, position: Vec2, timestamp: float) -> None:
        ...

    def drag(self, position: Vec2, timestamp: float) -> None:
        ...

    def up(self, position: Vec2, timestamp: float, reason: str) -> None:
        ...


class MotionAwareGestureSink(GestureSink, Protocol):
    """Optional sink extension for separating logical and pointer motion."""

    def drag_frame(self, frame: MotionFrame) -> None:
        ...


class MotionObservationSink(GestureSink, Protocol):
    """Optional extension for logical frames which post no pointer event."""

    def observe_motion_frame(self, frame: MotionFrame) -> None:
        ...


class TransportAwareGestureSink(GestureSink, Protocol):
    """Optional extension for a timed, single-owner pointer transport."""

    def service_transport(self, timestamp: float) -> TransportStep:
        ...

    def next_transport_deadline(self) -> Optional[float]:
        ...


class RecordingSink:
    """Thread-safe sink that records events and never injects mouse input."""

    def __init__(self) -> None:
        self._events: List[PointerEvent] = []
        self._motion_observations: List[MotionFrame] = []
        self._lock = Lock()

    def down(self, position: Vec2, timestamp: float) -> None:
        self._append(PointerEventKind.DOWN, position, timestamp)

    def drag(self, position: Vec2, timestamp: float) -> None:
        self._append(PointerEventKind.DRAG, position, timestamp)

    def drag_frame(self, frame: MotionFrame) -> None:
        """Record rich motion while preserving the traditional event shape."""

        self._append(
            PointerEventKind.DRAG,
            frame.logical_after,
            frame.timestamp,
            motion=frame,
        )

    def observe_motion_frame(self, frame: MotionFrame) -> None:
        """Record a logical no-op without inventing a pointer event.

        This is used for a radial step which is clamped at the exact rim.  The
        feedback layer needs the clamp metadata, while DOWN/DRAG/UP must remain
        empty when no physical displacement exists.
        """

        with self._lock:
            self._motion_observations.append(frame)

    def up(self, position: Vec2, timestamp: float, reason: str = "idle") -> None:
        self._append(PointerEventKind.UP, position, timestamp, reason)

    def _append(
        self,
        kind: PointerEventKind,
        position: Vec2,
        timestamp: float,
        reason: str = "",
        motion: Optional[MotionFrame] = None,
    ) -> None:
        with self._lock:
            self._events.append(PointerEvent(kind, position, timestamp, reason, motion))

    @property
    def events(self) -> List[PointerEvent]:
        """Return a snapshot so callers cannot mutate the recording."""

        with self._lock:
            return list(self._events)

    @property
    def motion_observations(self) -> List[MotionFrame]:
        """Return logical frames that intentionally posted no pointer event."""

        with self._lock:
            return list(self._motion_observations)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._motion_observations.clear()
