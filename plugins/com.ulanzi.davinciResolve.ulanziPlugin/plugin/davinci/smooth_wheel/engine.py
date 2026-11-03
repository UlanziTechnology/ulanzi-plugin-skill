# Copyright (c) Ulanzi DaVinci Resolve plugin contributors.
# Migrated from this project's validated gesture lab (tourbox-wheel-lab/src/tourbox_wheel_lab/engine.py, v0.1.20).
# This is first-party experimental code promoted into the formal candidate;
# keep host-specific pointer and recognition policy outside this pure core.

"""Lossless, fixed-rate color-wheel gesture scheduling.

The engine is deliberately independent from Ulanzi and from real mouse APIs.
Inputs are accumulated as signed mode segments.  A call to :meth:`step`
consumes at most one configured slice, making tests deterministic and ensuring
a delayed scheduler frame never replays a burst of historical pointer paths.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import math
from threading import Event, RLock, Thread, current_thread
import time
from typing import Callable, Deque, Dict, Optional, Union

from .geometry import Vec2, WheelModel
from .sinks import GestureSink, MotionFrame, TransportStep


class GestureMode(str, Enum):
    ORBIT = "orbit"
    PUSH_PULL = "push_pull"


@dataclass(frozen=True)
class GestureConfig:
    """Timing and per-frame limits for the research scheduler."""

    frame_hz: float = 120.0
    idle_timeout: float = 0.210
    min_down_interval: float = 0.0
    watchdog_timeout: float = 1.0
    max_angle_per_frame: float = 4.0
    max_radial_per_frame: float = 2.0
    epsilon: float = 1e-9
    axis_alignment_step: float = 0.0
    orbit_alignment_step: float = 0.0
    max_flick_angle_per_frame: float = 0.0
    flick_accel_per_frame: float = 0.0
    max_flick_radial_per_frame: float = 0.0
    radial_accel_per_frame: float = 0.0
    continuous_orbit: bool = False
    orbit_pacing_window: float = 0.0
    orbit_pacing_max_window: float = 0.0

    def __post_init__(self) -> None:
        positive = {
            "frame_hz": self.frame_hz,
            "idle_timeout": self.idle_timeout,
            "watchdog_timeout": self.watchdog_timeout,
            "max_angle_per_frame": self.max_angle_per_frame,
            "max_radial_per_frame": self.max_radial_per_frame,
            "epsilon": self.epsilon,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError("%s must be finite and greater than zero" % name)
        if not math.isfinite(self.min_down_interval) or self.min_down_interval < 0.0:
            raise ValueError("min_down_interval must be finite and non-negative")
        if not math.isfinite(self.axis_alignment_step) or self.axis_alignment_step < 0.0:
            raise ValueError("axis_alignment_step must be finite and non-negative")
        if not math.isfinite(self.orbit_alignment_step) or self.orbit_alignment_step < 0.0:
            raise ValueError("orbit_alignment_step must be finite and non-negative")
        if not math.isfinite(self.max_flick_angle_per_frame) or self.max_flick_angle_per_frame < 0.0:
            raise ValueError("max_flick_angle_per_frame must be finite and non-negative")
        if not math.isfinite(self.flick_accel_per_frame) or self.flick_accel_per_frame < 0.0:
            raise ValueError("flick_accel_per_frame must be finite and non-negative")

        if (not math.isfinite(self.orbit_pacing_window)
                or not 0 <= self.orbit_pacing_window <= 0.080):
            raise ValueError("orbit_pacing_window must be finite and between 0 and .080")
        if (not math.isfinite(self.orbit_pacing_max_window)
                or not 0 <= self.orbit_pacing_max_window <= 0.080
                or (self.orbit_pacing_max_window > 0
                    and self.orbit_pacing_max_window < self.orbit_pacing_window)):
            raise ValueError("orbit_pacing_max_window must be zero or between the base window and .080")
        for name in ("max_flick_radial_per_frame", "radial_accel_per_frame"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError("%s must be finite and non-negative" % name)


@dataclass(frozen=True)
class StepResult:
    """Observable result of one deterministic scheduler frame."""

    timestamp: float
    mode: Optional[GestureMode] = None
    consumed: float = 0.0
    began: bool = False
    dragged: bool = False
    ended: bool = False
    cancelled: bool = False
    reason: str = ""
    next_wakeup_at: Optional[float] = None


@dataclass(frozen=True)
class EngineSnapshot:
    session_active: bool
    active_mode: Optional[GestureMode]
    fresh_handle_required: bool
    fresh_handle_epoch: int
    pending_angle: float
    pending_radial: float
    submitted_angle: float
    submitted_radial: float
    consumed_angle: float
    consumed_radial: float
    last_input_at: Optional[float]
    handle: Vec2
    radius: float
    effective_max_radius: float
    last_nonzero_axis: Vec2
    diameter_axis: Vec2
    signed_radius: float
    diameter_last_side: int
    motion_revision: int
    model_revision: int
    alignment_pending: bool = False
    alignment_active: bool = False
    alignment_remaining: float = 0.0
    alignment_mode: Optional[str] = None
    transport_pending: bool = False
    output_ready: bool = True
    cancelled: bool = False


@dataclass
class _Segment:
    mode: GestureMode
    amount: float
    frame_scale: float = 1.0


ModeLike = Union[GestureMode, str]


class GestureEngine:
    """Thread-safe input accumulator and continuous gesture session."""

    def __init__(
        self,
        model: WheelModel,
        sink: GestureSink,
        config: Optional[GestureConfig] = None,
        clock: Callable[[], float] = time.monotonic,
        last_down_at: Optional[float] = None,
    ) -> None:
        self._model = model
        self._sink = sink
        self._config = config or GestureConfig()
        self._clock = clock
        self._lock = RLock()
        self._pending: Deque[_Segment] = deque()
        self._session_active = False
        self._active_mode: Optional[GestureMode] = None
        self._axis_alignment = None
        self._alignment_mode = GestureMode.PUSH_PULL
        self._alignment_started = False
        self._flick_step = 0.0
        self._flick_output_at = None
        self._flick_mode = None
        # A visual safety barrier pauses pointer output without rejecting new
        # encoder input.  Deltas keep accumulating in ``_pending`` and resume
        # only after a trusted idle handle has been reconciled.
        self._fresh_handle_required = False
        self._fresh_handle_epoch = 0
        self._fresh_handle_reason = "fresh_handle_required"
        self._orbit_pacing_samples = deque(maxlen=8)
        self._orbit_pacing_direction = None
        self._orbit_pacing_started_at = None
        self._orbit_pacing_active_since = None
        self._orbit_pacing_until = 0.0
        self._orbit_pacing_adaptive_window = self._config.orbit_pacing_window
        self._last_input_at: Optional[float] = None
        self._last_step_at: Optional[float] = None
        self._last_down_at = last_down_at
        # Monotonic input/corrective-motion epoch used by visual feedback.
        # Increment on every admitted non-zero input, including inputs which
        # later cancel in the queue, so returning to the same coordinate cannot
        # make an old screenshot look current (the ABA case). Physical axis
        # alignment also advances it without changing encoder totals.
        self._motion_revision = 0
        # Separate model epoch for persistence/deduplication. Input admission
        # and visual CAS use ``motion_revision``; this value advances only when
        # a consumed frame or reconciliation mutates visible or hidden geometry.
        self._model_revision = 0
        # This receipt belongs to the model, not to the sink's pending queue.
        # A failed sink can discard that queue before the controller retires
        # the runner; its unsent model frame must remain unpublishable.
        self._output_ready = True
        self._cancelled = False
        self._submitted: Dict[GestureMode, float] = {
            GestureMode.ORBIT: 0.0,
            GestureMode.PUSH_PULL: 0.0,
        }
        self._consumed: Dict[GestureMode, float] = {
            GestureMode.ORBIT: 0.0,
            GestureMode.PUSH_PULL: 0.0,
        }

    @property
    def config(self) -> GestureConfig:
        return self._config

    def add_orbit(self, delta_degrees: float, now: Optional[float] = None) -> None:
        self.add(GestureMode.ORBIT, delta_degrees, now)

    def add_push_pull(self, delta_pixels: float, now: Optional[float] = None) -> None:
        self.add(GestureMode.PUSH_PULL, delta_pixels, now)

    def add(self, mode: ModeLike, delta: float, now: Optional[float] = None,
            *, orbit_frame_scale: float = 1.0, radial_frame_scale: float = 1.0) -> None:
        """Accumulate a signed input without blocking or truncating it.

        Adjacent inputs for the same mode are reduced to their signed sum.  A
        reversal therefore cancels work that has not yet reached the pointer,
        instead of replaying an obsolete tail before changing direction.
        """

        parsed_mode = GestureMode(mode)
        value = float(delta)
        if not math.isfinite(value):
            raise ValueError("delta must be finite")
        frame_scale = float(orbit_frame_scale)
        if not math.isfinite(frame_scale) or not 1.0 <= frame_scale <= 4.0:
            raise ValueError("orbit_frame_scale must be finite and between 1 and 4")
        radial_scale = float(radial_frame_scale)
        if not math.isfinite(radial_scale) or not 1.0 <= radial_scale <= 3.0:
            raise ValueError("radial_frame_scale must be finite and between 1 and 3")
        if parsed_mode is GestureMode.PUSH_PULL:
            frame_scale = radial_scale
        timestamp = self._clock() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("now must be finite")
        if abs(value) <= self._config.epsilon:
            return

        with self._lock:
            self._track_orbit_pacing_locked(parsed_mode, value, frame_scale, timestamp)
            self._motion_revision += 1
            self._submitted[parsed_mode] += value
            self._last_input_at = timestamp
            # Keep fast output permission attached to the input that earned
            # it; later medium input must retain its original frame size.
            # Reversals still cancel the contiguous same-mode tail losslessly,
            # including across different frame scales.
            while (self._pending and self._pending[-1].mode is parsed_mode
                   and self._pending[-1].amount * value < 0):
                segment = self._pending[-1]
                if abs(value) < abs(segment.amount):
                    segment.amount += value
                    if abs(segment.amount) <= self._config.epsilon:
                        self._pending.pop()
                    return
                value += self._pending.pop().amount
                if abs(value) <= self._config.epsilon:
                    return
            if (self._pending and self._pending[-1].mode is parsed_mode
                    and self._pending[-1].frame_scale == frame_scale):
                segment = self._pending[-1]
                segment.amount += value
                if abs(segment.amount) <= self._config.epsilon:
                    self._pending.pop()
            else:
                self._pending.append(_Segment(parsed_mode, value, frame_scale))

    def step(self, now: Optional[float] = None) -> StepResult:
        """Advance exactly one output frame.

        This method intentionally does not derive a catch-up count from elapsed
        time.  Even after a delayed frame it emits at most one DRAG and retains
        the unconsumed signed delta for later frames.
        """

        timestamp = self._clock() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("now must be finite")

        with self._lock:
            if (
                self._session_active
                and self._last_step_at is not None
                and timestamp - self._last_step_at >= self._config.watchdog_timeout
            ):
                self._last_step_at = timestamp
                self._cancel_locked(timestamp, "watchdog")
                return StepResult(
                    timestamp,
                    ended=True,
                    cancelled=True,
                    reason="watchdog",
                )

            self._last_step_at = timestamp
            transport = self._service_transport_locked(timestamp)
            if transport.handled:
                if transport.cancelled:
                    self._cancel_locked(timestamp, "sink_transport_cancelled")
                    return StepResult(
                        timestamp,
                        ended=True,
                        cancelled=True,
                        reason="sink_transport_cancelled",
                    )
                if transport.completed:
                    self._finish_output_locked()
                return StepResult(
                    timestamp,
                    reason=(
                        "sink_transport_complete"
                        if transport.completed
                        else "sink_transport"
                    ),
                    next_wakeup_at=transport.next_wakeup_at,
                )
            if self._fresh_handle_required:
                self._reset_flick_output_locked()
                # The owner runner performs the release after the visual
                # thread has only raised the barrier; native pointer I/O never
                # runs on the screenshot callback thread.
                if self._session_active:
                    self._end_session_locked(timestamp, self._fresh_handle_reason)
                    return StepResult(
                        timestamp,
                        ended=True,
                        reason=self._fresh_handle_reason,
                    )
                return StepResult(timestamp, reason="fresh_handle_required")
            if self._pending or self._alignment_started:
                # Keep queued deltas intact while a rapid re-arm is inside the
                # previous DOWN's double-click window. Normal idle releases
                # happen after that window, so normal bursts do not wait here.
                if (
                    not self._session_active
                    and self._last_down_at is not None
                    and timestamp - self._last_down_at < self._config.min_down_interval
                ):
                    return StepResult(timestamp, reason="click_guard")
                if self._axis_alignment is not None:
                    return self._align_one_locked(timestamp)
                return self._consume_one_locked(timestamp)

            self._reset_flick_output_locked()
            if (
                self._session_active
                and self._last_input_at is not None
                and timestamp - self._last_input_at >= self._config.idle_timeout
            ):
                self._end_session_locked(timestamp, "idle")
                return StepResult(timestamp, ended=True, reason="idle")

            return StepResult(timestamp)

    def _service_transport_locked(self, timestamp: float) -> TransportStep:
        """Advance an optional sink transport before consuming another frame."""

        service = getattr(self._sink, "service_transport", None)
        if not callable(service):
            return TransportStep(False)
        result = service(timestamp)
        if not isinstance(result, TransportStep):
            raise TypeError("service_transport must return TransportStep")
        wakeup = result.next_wakeup_at
        if wakeup is not None and not math.isfinite(wakeup):
            raise ValueError("transport wakeup must be finite")
        return result

    def _next_transport_deadline_locked(self) -> Optional[float]:
        resolver = getattr(self._sink, "next_transport_deadline", None)
        if not callable(resolver):
            return None
        deadline = resolver()
        if deadline is None:
            return None
        value = float(deadline)
        if not math.isfinite(value):
            raise ValueError("transport deadline must be finite")
        return value

    def cancel(self, now: Optional[float] = None, reason: str = "cancel") -> bool:
        """Abort pending work and release an active pointer exactly once."""

        timestamp = self._clock() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("now must be finite")
        with self._lock:
            had_session = self._session_active
            self._cancel_locked(timestamp, reason)
            self._last_step_at = timestamp
            return had_session

    def snapshot(self) -> EngineSnapshot:
        with self._lock:
            pending_angle = 0.0
            pending_radial = 0.0
            for segment in self._pending:
                if segment.mode is GestureMode.ORBIT:
                    pending_angle += segment.amount
                else:
                    pending_radial += segment.amount
            return EngineSnapshot(
                session_active=self._session_active,
                active_mode=self._active_mode,
                fresh_handle_required=self._fresh_handle_required,
                fresh_handle_epoch=self._fresh_handle_epoch,
                pending_angle=pending_angle,
                pending_radial=pending_radial,
                submitted_angle=self._submitted[GestureMode.ORBIT],
                submitted_radial=self._submitted[GestureMode.PUSH_PULL],
                consumed_angle=self._consumed[GestureMode.ORBIT],
                consumed_radial=self._consumed[GestureMode.PUSH_PULL],
                last_input_at=self._last_input_at,
                handle=self._model.handle,
                radius=self._model.radius,
                effective_max_radius=self._model.effective_max_radius,
                last_nonzero_axis=self._model.last_nonzero_axis,
                diameter_axis=self._model.diameter_axis,
                signed_radius=self._model.signed_radius,
                diameter_last_side=self._model.diameter_last_side,
                motion_revision=self._motion_revision,
                model_revision=self._model_revision,
                alignment_pending=self._axis_alignment is not None,
                alignment_active=self._alignment_started,
                alignment_mode=(self._alignment_mode.value if self._axis_alignment else None),
                alignment_remaining=(
                    (self._axis_alignment[1] - self._axis_alignment[0]).length
                    if self._axis_alignment is not None else 0.0
                ),
                # Read under the same owner lock as the planned geometry. A
                # staged native frame must not appear committed to observers.
                transport_pending=self._next_transport_deadline_locked() is not None,
                # A retired sink rejects all further output. That does not
                # revoke a receipt for its already completed final geometry;
                # cancelled independently blocks still-active publication.
                output_ready=(self._output_ready and
                              (self._cancelled or self._sink_output_ready_locked())),
                cancelled=self._cancelled,
            )

    def reconcile_idle_handle(
        self,
        confirmed: Vec2,
        expected: Vec2,
        *,
        preserve_diameter_axis: bool = False,
        restore_orbit_path: bool = False,
        effective_max_radius: Optional[float] = None,
        tolerance: float = 1.5,
        expected_motion_revision: Optional[int] = None,
        expected_fresh_epoch: Optional[int] = None,
    ) -> Optional[Vec2]:
        """Apply one visual checkpoint only at a completely idle boundary.

        ``expected`` is captured with the screenshot request. Comparing it
        again under the engine lock prevents a late observation from changing
        a newer predicted path. No sink method is called here, so visual I/O
        can never enter or stall the pointer lifecycle.
        """

        parsed_tolerance = float(tolerance)
        if not math.isfinite(parsed_tolerance) or parsed_tolerance < 0.0:
            raise ValueError("tolerance must be finite and non-negative")
        with self._lock:
            if self._fresh_handle_required:
                # Encoder callbacks admitted while paused intentionally advance
                # motion_revision even though the model is frozen.  The fresh
                # barrier epoch, plus the expected handle comparison below, is
                # the authoritative CAS for this recovery path.
                if expected_fresh_epoch != self._fresh_handle_epoch:
                    return None
            elif (
                expected_motion_revision is not None
                and self._motion_revision != expected_motion_revision
            ):
                return None
            if self._session_active:
                return None
            # A freshness barrier deliberately retains lossless input while
            # output is paused.  Its capture is therefore allowed to reconcile
            # with queued motion, which has not touched the model yet.
            if self._pending and not self._fresh_handle_required:
                return None
            if (self._model.handle - expected).length > parsed_tolerance:
                return None
            if restore_orbit_path:
                # A trusted outer-orbit observation describes transport error,
                # not a user request to shrink the orbit. Keep the intended
                # model point and repair the physical offset on the owner
                # runner, only when queued/new user input resumes motion.
                offset = confirmed - self._model.center
                target = self._model.handle
                limit = self._model.effective_max_radius
                if (preserve_diameter_axis or effective_max_radius is not None
                        or self._config.orbit_alignment_step <= 0
                        or not math.isfinite(offset.length)
                        or self._model.radius < .90 * self._model.max_radius
                        or not .30 * self._model.max_radius <= offset.length <= limit + 2.5
                        or offset.dot(target - self._model.center) <= 0
                        or (confirmed - target).length > .65 * self._model.max_radius):
                    return None
                self._axis_alignment = (confirmed, target)
                self._alignment_mode = GestureMode.ORBIT
                self._alignment_started = False
                self._model_revision += 1
                self._output_ready = True
                return target
            align = preserve_diameter_axis and self._config.axis_alignment_step > 0
            if align:
                # Bound the proposed physical correction before changing the
                # model. A distant/incorrect visual detection must never start
                # a large autonomous sweep on the next encoder event.
                offset = confirmed - self._model.center
                limit = (self._model.effective_max_radius
                         if effective_max_radius is None else effective_max_radius)
                if not math.isfinite(offset.length) or not math.isfinite(limit) or limit <= 0:
                    return None
                projected_offset = (offset.normalized() * limit
                                    if offset.length > limit else offset)
                projected = (self._model.center + self._model.diameter_axis
                             * projected_offset.dot(self._model.diameter_axis))
                if (confirmed - projected).length > limit * 0.25:
                    return None
            if effective_max_radius is not None:
                self._model.set_effective_max_radius(effective_max_radius)
            adopted = self._model.reconcile_handle(
                confirmed,
                preserve_diameter_axis=preserve_diameter_axis,
            )
            self._axis_alignment = (
                (confirmed, adopted)
                if align and (confirmed - adopted).length > 1.5 else None
            )
            self._alignment_mode = GestureMode.PUSH_PULL
            self._alignment_started = False
            # ``motion_revision`` is the admitted-input CAS observed by the
            # screenshot. Reconciliation consumes no new input, so retaining
            # that epoch lets the just-applied observation be promoted to a
            # confirmed checkpoint. ``model_revision`` independently records
            # the authoritative geometry mutation for persistence dedupe.
            self._model_revision += 1
            self._output_ready = True
            return adopted

    def require_fresh_handle(
        self,
        *,
        reason: str = "fresh_handle_required",
    ) -> int:
        """Pause output at the next owner-runner frame.

        New encoder input remains lossless because :meth:`add` still appends to
        the normal queue.  This method performs no sink I/O: the runner remains
        the sole owner of the eventual UP, so a visual callback can never block
        inside a native pointer post while holding the engine lock.
        """

        with self._lock:
            self._reset_orbit_pacing_locked()
            if not self._fresh_handle_required:
                self._fresh_handle_epoch += 1
                self._fresh_handle_required = True
            self._fresh_handle_reason = str(reason or "fresh_handle_required")
            return self._fresh_handle_epoch

    def release_fresh_handle(
        self,
        fresh_epoch: int,
        adopted: Vec2,
        *,
        tolerance: float = 1e-6,
    ) -> bool:
        """Resume a paused queue after feedback committed ``adopted``.

        Pending input is allowed and intentionally preserved.  No pointer can
        begin while the barrier is set, so matching the reconciled model point
        is sufficient to release the queue without an ABA window.
        """

        parsed_tolerance = float(tolerance)
        if not math.isfinite(parsed_tolerance) or parsed_tolerance < 0.0:
            raise ValueError("tolerance must be finite and non-negative")
        with self._lock:
            if (
                not self._fresh_handle_required
                or self._fresh_handle_epoch != fresh_epoch
                or self._session_active
            ):
                return False
            if (self._model.handle - adopted).length > parsed_tolerance:
                return False
            self._fresh_handle_required = False
            self._fresh_handle_reason = "fresh_handle_required"
            return True

    def _align_one_locked(self, timestamp: float) -> StepResult:
        """Close a trusted visual offset before consuming new user motion.

        Planning never posts a mouse event. Only the owner runner may execute
        this bounded path, after user input and the ordinary click guard. The
        fixed model diameter and encoder totals remain untouched.
        """
        self._reset_flick_output_locked()
        self._output_ready = False
        before, target = self._axis_alignment
        distance = (target - before).length
        orbit = self._alignment_mode is GestureMode.ORBIT
        purpose = "orbit_alignment" if orbit else "axis_alignment"
        limit = self._config.orbit_alignment_step if orbit else self._config.axis_alignment_step
        step = min(distance, limit)
        after = target if step >= distance else before + (target - before) * (step / distance)
        began = not self._session_active
        self._alignment_started = True
        # Include corrective output in the visual CAS epoch so a screenshot
        # taken during alignment cannot later overwrite the finished path.
        self._motion_revision += 1
        if began:
            self._sink.down(before, timestamp)
            self._last_down_at = timestamp
            self._session_active = True
        frame = MotionFrame(
            mode=self._alignment_mode.value, logical_before=before, logical_after=after,
            logical_applied=0.0, timestamp=timestamp, purpose=purpose,
        )
        drag_frame = getattr(self._sink, "drag_frame", None)
        if callable(drag_frame):
            drag_frame(frame)
        else:
            self._sink.drag(after, timestamp)
        if after == target:
            self._axis_alignment = None
            self._alignment_started = False
            self._motion_revision += 1
        else:
            self._axis_alignment = (after, target)
        transport_deadline = self._finish_output_locked()
        return StepResult(timestamp, mode=self._alignment_mode, began=began,
                          dragged=True, reason=purpose,
                          next_wakeup_at=transport_deadline)

    def _finish_output_locked(self) -> Optional[float]:
        deadline = self._next_transport_deadline_locked()
        # A synchronous output or deliberate zero-displacement frame is done.
        # Staged output needs an explicit TransportStep.completed receipt.
        self._output_ready = deadline is None and self._sink_output_ready_locked()
        return deadline

    def _sink_output_ready_locked(self) -> bool:
        # Native cancellation can return normally after dropping a post. The
        # Windows sink supplies its own receipt so no-pending alone cannot
        # turn that silent cancellation into a successful model publication.
        ready = getattr(self._sink, "model_output_ready", None)
        return bool(ready()) if callable(ready) else True

    def _reset_flick_output_locked(self) -> None:
        self._flick_step = 0.0
        self._flick_output_at = None
        self._flick_mode = None

    def _consume_flick_block_locked(self, timestamp: float) -> float:
        """One velocity-limited slice across contiguous fast input segments.

        Input segments describe permission and distance, not separate gestures.
        Brake against the whole fast block so a segment boundary cannot create
        a false stop/restart. Never cross a normal-speed, mode or direction boundary.
        """
        head = self._pending[0]
        direction = math.copysign(1.0, head.amount)
        distance = 0.0
        scale = 1.0
        for segment in self._pending:
            if (segment.mode is not head.mode
                    or segment.frame_scale <= 1.0
                    or segment.amount * direction <= 0):
                break
            distance += abs(segment.amount)
            scale = max(scale, segment.frame_scale)
        orbit = head.mode is GestureMode.ORBIT
        base = self._config.max_angle_per_frame if orbit else self._config.max_radial_per_frame
        ceiling = self._config.max_flick_angle_per_frame if orbit else self._config.max_flick_radial_per_frame
        cap = min(base * scale, max(base, ceiling))
        accel = self._config.flick_accel_per_frame if orbit else self._config.radial_accel_per_frame
        previous = abs(self._flick_step)
        if (self._flick_mode is not head.mode or self._flick_step * direction <= 0 or self._flick_output_at is None
                or timestamp - self._flick_output_at > 0.050
                or timestamp <= self._flick_output_at):
            previous = 0.0
        # Exact discrete stopping budget: n*v - a*n*(n-1)/2 == d, with
        # n=ceil(v/a). This includes the final partial frame, avoiding a
        # small speed discontinuity introduced by a continuous sqrt bound.
        # Limiting the increase per emitted frame also prevents a late runner
        # from jumping ahead. Cancellation/reversal always outrank easing.
        stop_frames = max(1, math.ceil((math.sqrt(1.0 + 8.0 * distance / accel) - 1.0) / 2.0))
        brake = distance / stop_frames + accel * (stop_frames - 1) / 2.0
        # A lower desired scale in a later fast segment also eases down;
        # absolute frame and stopping-distance limits remain authoritative.
        step = min(distance, max(base, ceiling),
                   max(cap, previous - accel), previous + accel, brake)
        remaining = step
        while remaining > self._config.epsilon:
            segment = self._pending[0]
            taken = min(remaining, abs(segment.amount))
            segment.amount -= direction * taken
            remaining -= taken
            if abs(segment.amount) <= self._config.epsilon:
                self._pending.popleft()
        self._flick_step = direction * step
        self._flick_output_at = timestamp
        self._flick_mode = head.mode
        return self._flick_step

    def _reset_orbit_pacing_locked(self) -> None:
        self._orbit_pacing_samples.clear()
        self._orbit_pacing_direction = None
        self._orbit_pacing_started_at = None
        self._orbit_pacing_active_since = None
        self._orbit_pacing_until = 0.0
        self._orbit_pacing_adaptive_window = self._config.orbit_pacing_window

    def _track_orbit_pacing_locked(self, mode, amount, scale, timestamp) -> None:
        """Only a sustained turn earns a short, finite scheduling horizon."""
        if (not self._config.continuous_orbit or self._config.orbit_pacing_window <= 0
                or mode is not GestureMode.ORBIT or self._fresh_handle_required):
            self._reset_orbit_pacing_locked()
            return
        direction = math.copysign(1.0, amount)
        samples = self._orbit_pacing_samples
        if (self._orbit_pacing_direction != direction or not samples
                or not 0 < timestamp - samples[-1][0] <= 0.120):
            self._reset_orbit_pacing_locked()
            self._orbit_pacing_direction = direction
            self._orbit_pacing_started_at = timestamp
        samples.append((timestamp, scale))
        eligible = (len(samples) >= 6
                    and timestamp - self._orbit_pacing_started_at >= 0.120
                    and (timestamp - samples[0][0]) / (len(samples) - 1) <= 0.050
                    and sum(s > 1.0 for _, s in samples) >= 3)
        if not eligible:
            self._orbit_pacing_active_since = None
            self._orbit_pacing_until = 0.0
            return
        if self._orbit_pacing_active_since is None:
            self._orbit_pacing_active_since = timestamp
        ramp = min(1.0, (timestamp - self._orbit_pacing_active_since) / 0.060)
        window = self._config.orbit_pacing_window
        maximum = self._config.orbit_pacing_max_window
        if maximum > window:
            # Recent sparse packets need a little more reserved travel than
            # tightly spaced packets. Smooth the horizon itself so one long
            # interval cannot abruptly slow the output. Never predict distance.
            recent_gap = max(b[0] - a[0] for a, b in zip(samples, list(samples)[1:]))
            target = max(window, min(maximum, recent_gap * 1.35))
            self._orbit_pacing_adaptive_window += .25 * (
                target - self._orbit_pacing_adaptive_window)
            window = self._orbit_pacing_adaptive_window
        self._orbit_pacing_until = timestamp + window * ramp

    def _consume_continuous_orbit_locked(self, timestamp: float) -> float:
        """Share one frame across speed boundaries without stopping inside a turn.

        A normal segment still costs one frame per base-sized slice. Adjacent
        fast segments retain the existing shared maximum permission. Fractional
        leftovers spend only their fraction of the frame; the next same-direction
        segment can use the remainder. Brake only against the actual queue end.
        """
        head = self._pending[0]
        direction = math.copysign(1.0, head.amount)
        base = self._config.max_angle_per_frame
        ceiling = max(base, self._config.max_flick_angle_per_frame)
        accel = self._config.flick_accel_per_frame
        previous = abs(self._flick_step)
        if (self._flick_mode is not head.mode or self._flick_step * direction <= 0
                or self._flick_output_at is None
                or not 0 < timestamp - self._flick_output_at <= 0.050):
            previous = 0.0

        # Group fast permissions as before, but include normal intervals in
        # the stopping horizon. Modes and directions remain hard boundaries.
        groups = []
        distance = 0.0
        for segment in self._pending:
            if segment.mode is not head.mode or segment.amount * direction <= 0:
                break
            length = abs(segment.amount)
            fast = segment.frame_scale > 1.0
            cap = min(base * segment.frame_scale, ceiling)
            if groups and groups[-1][2] == fast:
                groups[-1][0] += length
                groups[-1][1] = max(groups[-1][1], cap)
            else:
                groups.append([length, cap, fast])
            distance += length
        budget = 1.0
        capacity = 0.0
        for length, cap, fast in groups:
            # Retain the established gradual reduction between fast scales;
            # normal input never borrows that permission.
            if fast:
                cap = max(cap, previous - accel)
            taken = min(length, budget * cap)
            capacity += taken
            budget -= taken / cap
            if budget <= self._config.epsilon:
                break
        stop_frames = max(1, math.ceil(
            (math.sqrt(1.0 + 8.0 * distance / accel) - 1.0) / 2.0))
        brake = distance / stop_frames + accel * (stop_frames - 1) / 2.0
        step = min(distance, capacity, ceiling, previous + accel, brake)
        horizon = self._orbit_pacing_until - timestamp
        if horizon > 0:
            frames_left = max(1, math.ceil(horizon * self._config.frame_hz))
            # Spend only already received distance. The fixed last-input
            # deadline prevents an asymptotic tail after the user stops.
            paced = distance / frames_left
            step = min(step, max(paced, previous - accel))
        remaining = step
        while remaining > self._config.epsilon:
            segment = self._pending[0]
            taken = min(remaining, abs(segment.amount))
            segment.amount -= direction * taken
            remaining -= taken
            if abs(segment.amount) <= self._config.epsilon:
                self._pending.popleft()
        self._flick_step = direction * step
        self._flick_output_at = timestamp
        self._flick_mode = head.mode
        return self._flick_step

    def _consume_one_locked(self, timestamp: float) -> StepResult:
        self._output_ready = False
        segment = self._pending[0]
        limit = (
            self._config.max_angle_per_frame
            if segment.mode is GestureMode.ORBIT
            else self._config.max_radial_per_frame
        )
        accel = (self._config.flick_accel_per_frame if segment.mode is GestureMode.ORBIT
                 else self._config.radial_accel_per_frame)
        continuous = (self._config.continuous_orbit
                      and segment.mode is GestureMode.ORBIT and accel > 0.0)
        smooth_flick = continuous or (segment.frame_scale > 1.0 and accel > 0.0)
        if continuous:
            amount = self._consume_continuous_orbit_locked(timestamp)
        elif smooth_flick:
            amount = self._consume_flick_block_locked(timestamp)
        else:
            self._reset_flick_output_locked()
        if not smooth_flick and segment.mode is GestureMode.ORBIT and segment.frame_scale > 1.0:
            fast_limit = min(limit * segment.frame_scale,
                             max(limit, self._config.max_flick_angle_per_frame))
            # Ease the last few fast frames back toward the normal slice.
            limit = min(fast_limit, max(limit, abs(segment.amount) / 4.0))
        if not smooth_flick:
            amount = max(-limit, min(limit, segment.amount))
            segment.amount -= amount
            if abs(segment.amount) <= self._config.epsilon:
                self._pending.popleft()

        began = False
        self._switch_mode_locked(segment.mode)
        before = self._model.handle
        if segment.mode is GestureMode.ORBIT:
            result = self._model.orbit(amount)
        else:
            result = self._model.push_pull(amount)
        if abs(result.applied) > self._config.epsilon:
            self._model_revision += 1
        after = getattr(result, "position", self._model.handle)
        self._consumed[segment.mode] += amount

        dragged = after != before
        frame = MotionFrame(
            mode=segment.mode.value,
            logical_before=before,
            logical_after=after,
            logical_applied=result.applied,
            timestamp=timestamp,
            clamped=result.clamped,
            crossed_center=result.crossed_center,
        )
        if dragged:
            # Orbit at the exact center and a clamped radial step must not
            # produce a click-only gesture that a host could treat as reset.
            if not self._session_active:
                self._sink.down(before, timestamp)
                self._last_down_at = timestamp
                self._session_active = True
                began = True
            drag_frame = getattr(self._sink, "drag_frame", None)
            if callable(drag_frame):
                drag_frame(frame)
            else:
                # Compatibility path for existing sinks that only implement
                # the original absolute-position API.
                self._sink.drag(after, timestamp)
        elif result.clamped:
            # Reaching the exact rim can make the next outward frame both
            # clamped and zero-displacement. Do not create a click-only host
            # lifecycle, but let an optional feedback sink observe the clamp
            # so its terminal screenshot can learn Resolve's effective limit.
            observe_frame = getattr(self._sink, "observe_motion_frame", None)
            if callable(observe_frame):
                observe_frame(frame)
        transport_deadline = self._finish_output_locked()
        return StepResult(
            timestamp,
            mode=segment.mode,
            consumed=amount,
            began=began,
            dragged=dragged,
            next_wakeup_at=transport_deadline,
        )

    def _switch_mode_locked(self, mode: GestureMode) -> None:
        if self._active_mode is mode:
            return
        if self._active_mode is GestureMode.PUSH_PULL:
            self._model.end_push_pull()
        if mode is GestureMode.PUSH_PULL:
            self._model.begin_push_pull()
        self._active_mode = mode

    def _end_session_locked(self, timestamp: float, reason: str) -> None:
        self._reset_orbit_pacing_locked()
        self._reset_flick_output_locked()
        if not self._session_active:
            return
        if self._active_mode is GestureMode.PUSH_PULL:
            self._model.end_push_pull()
        self._active_mode = None
        self._sink.up(self._model.handle, timestamp, reason)
        self._session_active = False

    def _cancel_locked(self, timestamp: float, reason: str) -> None:
        # Set before UP: even cleanup failure must close the controller's
        # short still-armed snapshot window. Preserve the output receipt so a
        # normal, safely retired session can persist its last completed frame.
        self._cancelled = True
        self._reset_flick_output_locked()
        self._pending.clear()
        self._axis_alignment = None
        self._alignment_started = False
        self._end_session_locked(timestamp, reason)


class GestureRunner:
    """A 120 Hz-by-default runner with monotonic, skip-ahead deadlines."""

    def __init__(
        self,
        engine: GestureEngine,
        clock: Callable[[], float] = time.monotonic,
        wait_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._stop = Event()
        self._wait = wait_fn if wait_fn is not None else self._stop.wait
        self._terminated = Event()
        self._thread: Optional[Thread] = None
        self._lock = RLock()
        self._heartbeat_at = self._clock()

    @property
    def heartbeat_at(self) -> float:
        # Read without taking the engine/sink lock: the independent watchdog
        # must still observe a stalled step while it owns those locks.
        return self._heartbeat_at

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._terminated.clear()
            self._heartbeat_at = self._clock()
            self._thread = Thread(target=self._run, name="wheel-gesture-runner", daemon=True)
            self._thread.start()

    def request_stop(self) -> None:
        """Prevent another scheduler frame without waiting on engine/sink locks."""

        self._stop.set()

    def join(self, timeout: Optional[float] = None) -> bool:
        """Wait for the runner only; return whether its thread has terminated."""

        with self._lock:
            thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def stop(self, timeout: float = 1.0, cancel: bool = True) -> bool:
        """Request stop and wait at most ``timeout`` seconds.

        A timed-out runner may still own the engine lock inside a sink/native
        post.  Never call ``engine.cancel`` from the waiting thread in that
        case; the runner performs logical cancellation in its own ``finally``
        block after the in-flight frame returns.
        """

        self.request_stop()
        with self._lock:
            thread = self._thread
        stopped = self.join(timeout)
        if cancel and stopped and thread is None:
            self._engine.cancel(self._clock(), "runner_stop")
        return stopped

    def _run(self) -> None:
        period = 1.0 / self._engine.config.frame_hz
        deadline = self._clock()
        try:
            while not self._stop.is_set():
                now = self._clock()
                remaining = deadline - now
                if remaining > 0.0:
                    self._wait(remaining)
                    continue

                # Exactly one frame of work.  Missed deadlines are skipped,
                # rather than replayed in a tight catch-up loop.
                result = self._engine.step(now)
                completed_at = self._clock()
                self._heartbeat_at = completed_at
                # A cancelled frame has ended the pointer/model generation.
                # Continuing this runner could consume future input from a
                # model which advanced farther than the last safe host point.
                # The controller safety loop observes termination and retires
                # the complete generation before another arm.
                if getattr(result, "cancelled", False):
                    break
                wakeup = getattr(result, "next_wakeup_at", None)
                deadline = self.scheduled_deadline(
                    deadline,
                    now,
                    period,
                    wakeup,
                    transport_completed=(
                        getattr(result, "reason", "")
                        == "sink_transport_complete"
                    ),
                    completed_at=completed_at,
                )
        finally:
            try:
                # Any exception or external stop must not leave a logical
                # button down. This runs on the owner thread, so it cannot make
                # another thread wait on a stuck engine lock.
                self._engine.cancel(self._clock(), "runner_exit")
            finally:
                self._terminated.set()

    @staticmethod
    def next_deadline(deadline: float, now: float, period: float) -> float:
        """Return the first cadence deadline strictly after ``now``."""

        candidate = deadline + period
        if candidate <= now:
            missed = math.floor((now - candidate) / period) + 1
            candidate += missed * period
        return candidate

    @classmethod
    def scheduled_deadline(
        cls,
        deadline: float,
        now: float,
        period: float,
        transport_wakeup: Optional[float] = None,
        *,
        transport_completed: bool = False,
        completed_at: Optional[float] = None,
    ) -> float:
        """Merge the normal cadence with one sink transport deadline.

        A transport wake becomes the current cadence origin. This intentionally
        leaves one full output period after the final anchor before normal
        motion resumes, closely matching the measured TourBox sequence and
        giving the host time to accept its new baseline.
        """

        if transport_completed:
            completion = now if completed_at is None else float(completed_at)
            if not math.isfinite(completion):
                raise ValueError("scheduler completion must be finite")
            return max(float(now), completion) + period
        candidate = cls.next_deadline(deadline, now, period)
        if transport_wakeup is None:
            return candidate
        wakeup = float(transport_wakeup)
        if not math.isfinite(wakeup):
            raise ValueError("scheduler wakeup must be finite")
        return min(candidate, max(now, wakeup))
