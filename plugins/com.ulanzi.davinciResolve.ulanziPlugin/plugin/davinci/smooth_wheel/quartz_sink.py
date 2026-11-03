"""Gesture sink that posts tagged CoreGraphics events through an interlock."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from threading import Condition, Event, Lock, RLock
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from .geometry import Vec2
from .sinks import TransportStep

from .interlock import InputInterlock
from .macos import MacOSBindings

if TYPE_CHECKING:
    from .sinks import MotionFrame


StateCallback = Callable[[bool], None]
TraceCallback = Callable[[dict], None]
# The TourBox trace showed that Resolve receives absolute locations at exactly
# 10x the predicted handle displacement while both mouse-delta fields stay 0.
LOGICAL_DELTA_SCALE = 0.0
# Shared smooth-wheel mapping from logical handle displacement to mouse travel.
# This is independent of the old per-step radial controller's input gain.
RESOLVE_LOCATION_SCALE = 10.0
DEFAULT_EDGE_MARGIN = 100.0
POST_EDGE_MARGIN = 2.0
# TourBox emits this exact tagged LEFT_DRAGGED location as a transport marker
# before restarting the held drag from a roomy screen location.  It is the one
# deliberate exception to the normal on-screen posting rule; it must never
# become an UP/failsafe endpoint.
REBASE_SENTINEL = Vec2(-10000.0, -10000.0)
# Measured from a passive TourBox trace: cursor transport begins about 7.7 ms
# after the sentinel and the first host-visible anchor arrives about 13.5 ms
# after it.  Use conservative integer-millisecond lower bounds so a delayed
# runner can never collapse warp and anchor into the same scheduler turn.
REBASE_WARP_DELAY = 0.007
REBASE_ANCHOR_DELAY = 0.013
REBASE_MIN_ANCHOR_AFTER_WARP = 0.005
# Establish a zero-displacement anchor before sending the pending logical
# frame. Keep that frame in a separate owner turn, including after slow posts.
REBASE_MOTION_AFTER_ANCHOR = 1.0 / 120.0
REBASE_CURSOR_POLL = 0.002
REBASE_CURSOR_TIMEOUT = 0.035
# A rim handle can be visible yet fail Resolve's first drag hit-test.  The
# passive TourBox/formal-plugin evidence uses the same outer threshold and an
# approximately five-pixel inward landing.  This offset is physical only: the
# logical/model anchor remains the detected handle position.
ORBIT_SAFE_PRESS_START_RATIO = 0.78
ORBIT_SAFE_PRESS_INSET_PX = 5.0


@dataclass
class _PendingRebase:
    phase: str
    sentinel_posted_at: float
    sentinel_at: float
    next_deadline: float
    rebase_point: Vec2
    candidate: Vec2
    logical_position: Vec2
    requested: Vec2
    previous_event_position: Vec2
    relative_delta: Optional[dict]
    logical: Optional[dict]
    warp_at: Optional[float] = None
    warp_completed_at: Optional[float] = None
    anchor_at: Optional[float] = None
    anchor_completed_at: Optional[float] = None
    cursor_candidate: Optional[Vec2] = None
    cursor_candidate_at: Optional[float] = None
    cursor_polls: int = 0
    origin_method: str = "explicit_warp"


class QuartzGestureSink:
    """A single-owner left-button lifecycle with an unconditional release path."""

    def __init__(
        self,
        bindings: MacOSBindings,
        interlock: InputInterlock,
        state_callback: Optional[StateCallback] = None,
        clock: Callable[[], float] = time.monotonic,
        trace_callback: Optional[TraceCallback] = None,
        detach_cursor: bool = False,
        location_scale: float = 1.0,
        display_bounds: Optional[Tuple[float, float, float, float]] = None,
        logical_bounds: Optional[Tuple[float, float, float, float]] = None,
        initial_anchor: Optional[Vec2] = None,
        edge_margin: float = DEFAULT_EDGE_MARGIN,
        target_pid: Optional[int] = None,
        observe_rebase_origin: bool = False,
    ) -> None:
        if not math.isfinite(location_scale) or location_scale <= 0.0:
            raise ValueError("location_scale must be finite and greater than zero")
        if not math.isfinite(edge_margin) or edge_margin < 0.0:
            raise ValueError("edge_margin must be finite and non-negative")
        if target_pid is not None and (
            not isinstance(target_pid, int)
            or isinstance(target_pid, bool)
            or target_pid <= 0
            or target_pid >= 2**31
        ):
            raise ValueError("target_pid must be a positive signed 32-bit integer")
        self._bindings = bindings
        self._interlock = interlock
        self._state_callback = state_callback or (lambda _down: None)
        self._clock = clock
        self._trace_callback = trace_callback
        self._lock = RLock()
        # Native CoreGraphics posts are synchronous and, in pathological
        # cases, may stop returning.  Cancellation therefore has a second,
        # short-lived coordination domain which is never the motion RLock.
        # It gates new DOWN/DRAG calls and keeps both CGEventSource objects
        # alive while any native call is in flight.
        self._lifecycle = Condition(Lock())
        self._release_requested = Event()
        self._physical_down = Event()
        self._cancel_epoch = 0
        self._active_native_calls = 0
        self._active_motion_calls = 0
        self._closed = False
        self._close_requested = False
        self._release_reason = ""
        self._failsafe_position = (0.0, 0.0)
        # ``_session_pending`` is a logical engine session. The real mouse
        # DOWN is deferred until the logical location actually changes, so an
        # exact no-op/clamped update cannot become a click.
        self._session_pending = False
        self._down = False
        self._last_logical_position = Vec2(0.0, 0.0)
        self._last_event_position = Vec2(0.0, 0.0)
        self._anchor: Optional[Vec2] = None
        self._model_position: Optional[Vec2] = None
        self._mapping_logical_anchor: Optional[Vec2] = None
        self._mapping_event_anchor: Optional[Vec2] = None
        self._orbit_safe_press: Optional[dict] = None
        self._pending_rebase: Optional[_PendingRebase] = None
        self._rebase_count = 0
        self._burst_rebase_count = 0
        self._detach_cursor = bool(detach_cursor)
        self._target_pid = target_pid
        self._observe_rebase_origin = bool(observe_rebase_origin)
        self._requested_location_scale = float(location_scale)
        self._location_scale = float(location_scale)
        self._display_bounds = self._normalize_bounds(display_bounds)
        self._logical_bounds = self._normalize_bounds(logical_bounds)
        if self._logical_bounds is not None and self._display_bounds is None:
            raise ValueError("logical_bounds requires display_bounds")
        self._edge_margin = float(edge_margin)
        self._safe_bounds = self._inset_bounds(
            self._display_bounds, POST_EDGE_MARGIN
        )
        self._rebase_bounds = self._inset_bounds(
            self._display_bounds, self._edge_margin
        )
        self._location_scale_status = self._resolve_location_scale(
            initial_anchor
        )
        self._cursor_detached = False
        self._source = self._bindings.create_mouse_source(self._interlock.tag)
        try:
            # A different source is essential: an UP must still be postable
            # when the motion source is stuck inside a synchronous DRAG post.
            self._failsafe_source = self._bindings.create_mouse_source(
                self._interlock.tag
            )
        except Exception:
            self._bindings.release_mouse_source(self._source)
            self._source = None
            raise
        self._last_event_at = self._clock()

    @property
    def owns_down(self) -> bool:
        # Conservative and lock-free: true covers both a completed DOWN and a
        # DOWN/DRAG currently admitted to CoreGraphics.
        return self._physical_down.is_set()

    @property
    def last_event_at(self) -> float:
        with self._lifecycle:
            return self._last_event_at

    @property
    def cleanup_pending(self) -> bool:
        with self._lifecycle:
            return not self._closed

    def location_scale_status(self) -> dict:
        """Return fixed-scale and edge-rebase diagnostics."""

        with self._lock:
            return self._location_scale_status_unlocked()

    def _location_scale_status_unlocked(self) -> dict:
        result = self._copy_scale_status(self._location_scale_status)
        pending = self._pending_rebase
        result["rebaseCount"] = self._rebase_count
        result["burstRebaseCount"] = self._burst_rebase_count
        result["rebasePending"] = pending is not None
        result["rebasePhase"] = None if pending is None else pending.phase
        result["rebaseNextDeadline"] = (
            None if pending is None else pending.next_deadline
        )
        result["rebaseWarpDelayMs"] = REBASE_WARP_DELAY * 1000.0
        result["rebaseAnchorDelayMs"] = REBASE_ANCHOR_DELAY * 1000.0
        result["rebaseMinAnchorAfterWarpMs"] = (
            REBASE_MIN_ANCHOR_AFTER_WARP * 1000.0
        )
        result["rebaseMotionAfterAnchorMs"] = REBASE_MOTION_AFTER_ANCHOR * 1000.0
        result["rebaseCursorVersion"] = "rebasecursor.1"
        result["observeRebaseOrigin"] = self._observe_rebase_origin
        result["rebaseOriginMethod"] = None if pending is None else pending.origin_method
        result["mappingLogicalAnchor"] = self._vec_dict(
            self._mapping_logical_anchor
        )
        result["mappingEventAnchor"] = self._vec_dict(
            self._mapping_event_anchor
        )
        result["orbitSafePress"] = self._copy_orbit_safe_press(
            self._orbit_safe_press
        )
        return result

    def next_transport_deadline(self) -> Optional[float]:
        """Return the next owner-runner deadline for a staged edge rebase."""

        with self._lock:
            if self._release_requested.is_set() or self._pending_rebase is None:
                return None
            return self._pending_rebase.next_deadline

    def service_transport(self, timestamp: float) -> TransportStep:
        """Advance at most one due edge-rebase phase on the gesture owner.

        No timer or helper thread posts CoreGraphics events.  Returning
        ``handled=True`` for every call that entered with a staged transport
        prevents the engine from consuming an ordinary logical frame in the
        same scheduler turn, including the turn that commits the pending frame.
        """

        now = float(timestamp)
        if not math.isfinite(now):
            raise ValueError("transport timestamp must be finite")
        with self._lock:
            pending = self._pending_rebase
            if pending is None:
                return TransportStep(False)
            phase = pending.phase
            if (
                self._release_requested.is_set()
                or not self._down
                or not self._physical_down.is_set()
            ):
                self._pending_rebase = None
                return TransportStep(True, "cancelled", cancelled=True)
            if now < pending.next_deadline:
                return TransportStep(True, phase, pending.next_deadline)

            try:
                if phase == "wait_warp":
                    self._validate_sentinel_display_topology()
                    origin = (self._read_rebase_origin(pending, now)
                              if self._observe_rebase_origin else "fallback")
                    if origin == "wait":
                        return TransportStep(True, "wait_cursor", pending.next_deadline)
                    if origin != "adopted":
                        if not self._warp_cursor(
                            pending.rebase_point, "edge_rebase_warp"
                        ):
                            self._pending_rebase = None
                            return TransportStep(True, "cancelled", cancelled=True)
                        pending.warp_at = self.last_event_at
                    # For adoption this is the last read completion, NOT a
                    # claimed CG warp. The trace distinguishes both pathways.
                    pending.warp_completed_at = self._clock()
                    pending.phase = "wait_anchor"
                    pending.next_deadline = max(
                        pending.sentinel_at + REBASE_ANCHOR_DELAY,
                        pending.warp_completed_at
                        + REBASE_MIN_ANCHOR_AFTER_WARP,
                    )
                    return TransportStep(
                        True, "warp", pending.next_deadline
                    )

                if phase == "wait_anchor":
                    self._validate_sentinel_display_topology()
                    # Both events establish the exact warped position only.
                    # They must not carry the pending frame's logical delta.
                    if not self._post(
                        "drag", pending.rebase_point, "edge_rebase_anchor",
                        trace_kind="edge_rebase_anchor",
                    ):
                        self._pending_rebase = None
                        return TransportStep(True, "cancelled", cancelled=True)
                    pending.anchor_at = self.last_event_at
                    self._last_event_position = pending.rebase_point
                    if not self._post(
                        "drag", pending.rebase_point, "edge_rebase_anchor_repeat",
                        trace_kind="edge_rebase_anchor_repeat",
                    ):
                        self._pending_rebase = None
                        return TransportStep(True, "cancelled", cancelled=True)
                    pending.anchor_completed_at = self._clock()
                    # Rebase the physical origin at the last committed logical
                    # point, not at the engine's already-planned next point.
                    self._mapping_logical_anchor = self._last_logical_position
                    self._mapping_event_anchor = pending.rebase_point
                    pending.phase = "wait_motion"
                    pending.next_deadline = (
                        pending.anchor_completed_at + REBASE_MOTION_AFTER_ANCHOR
                    )
                    return TransportStep(True, "anchor", pending.next_deadline)

                if phase != "wait_motion":
                    raise RuntimeError("unknown edge rebase transport phase")
                self._validate_sentinel_display_topology()
                if not self._post(
                    "drag",
                    pending.candidate,
                    "edge_rebase_motion",
                    relative_delta=pending.relative_delta,
                    logical=pending.logical,
                ):
                    self._pending_rebase = None
                    return TransportStep(True, "cancelled", cancelled=True)
                motion_at = self.last_event_at
                anchor_at = pending.anchor_at
                anchor_completed_at = pending.anchor_completed_at
                assert anchor_at is not None and anchor_completed_at is not None

                self._mapping_logical_anchor = pending.logical_position
                self._mapping_event_anchor = pending.candidate
                self._last_logical_position = pending.logical_position
                self._last_event_position = pending.candidate
                self._model_position = pending.logical_position
                self._rebase_count += 1
                self._burst_rebase_count += 1
                completed_at = self._clock()
                timing = {
                    "phase": "complete",
                    "originMethod": pending.origin_method,
                    "originPosition": self._vec_dict(pending.rebase_point),
                    "cursorPolls": pending.cursor_polls,
                    "sentinelAt": pending.sentinel_posted_at,
                    "sentinelCompletedAt": pending.sentinel_at,
                    "warpAt": pending.warp_at,
                    "warpCompletedAt": pending.warp_completed_at,
                    "anchorAt": anchor_at,
                    "anchorCompletedAt": anchor_completed_at,
                    "motionAt": motion_at,
                    "anchorToMotionMs": (motion_at - anchor_completed_at) * 1000.0,
                    "completedAt": completed_at,
                    "sentinelToWarpMs": (
                        None
                        if pending.warp_at is None
                        else (
                            pending.warp_at - pending.sentinel_posted_at
                        ) * 1000.0
                    ),
                    "sentinelCompletionToWarpMs": (
                        None
                        if pending.warp_at is None
                        else (pending.warp_at - pending.sentinel_at) * 1000.0
                    ),
                    "sentinelToAnchorMs": (
                        anchor_at - pending.sentinel_posted_at
                    ) * 1000.0,
                    "sentinelCompletionToAnchorMs": (
                        anchor_at - pending.sentinel_at
                    ) * 1000.0,
                    "warpToAnchorMs": (
                        None
                        if pending.warp_at is None
                        else (anchor_at - pending.warp_at) * 1000.0
                    ),
                }
                self._pending_rebase = None
                self._trace_control(
                    "edge_rebase",
                    "edge_threshold",
                    True,
                    from_position=pending.previous_event_position,
                    to_position=pending.candidate,
                    logical_position=pending.logical_position,
                    details=timing,
                )
                return TransportStep(True, "motion", completed=True)
            except Exception:
                reason = (
                    "cursor_rebase_failed"
                    if phase == "wait_warp"
                    else "mouse_drag_post_failed"
                )
                self._pending_rebase = None
                self._interlock.mark_cancel(reason)
                self.emergency_release(reason)
                if not self._physical_down.is_set():
                    self._mark_released()
                    self._discard_pending_session()
                raise

    def _read_rebase_origin(self, pending: _PendingRebase, now: float) -> str:
        """Read-only, bounded observation of the post-sentinel cursor origin.

        A reference trace showed a different real cursor position than the
        arithmetic full-display center. Do not assume who moved it or hardcode
        the measured offset. Accept only two stable central readings; otherwise
        keep the prior explicit-warp fallback and expose that fact in telemetry.
        """
        reader = getattr(self._bindings, "current_mouse_position", None)
        if not callable(reader):
            pending.origin_method = "fallback_reader_unavailable"
            return "fallback"
        started = self._clock()
        raw = reader()
        point = Vec2(float(raw[0]), float(raw[1]))
        read_at = self._clock()
        if not all(math.isfinite(v) for v in (point.x, point.y)):
            raise RuntimeError("non-finite rebase cursor observation")
        pending.cursor_polls += 1
        assert self._display_bounds is not None
        _, _, width, height = self._display_bounds
        center = pending.rebase_point
        candidate = Vec2(point.x + pending.requested.x * self._location_scale,
                         point.y + pending.requested.y * self._location_scale)
        eligible = (self._point_is_rebase_safe(point)
                    and self._point_is_rebase_safe(candidate)
                    and (point - center).length <= max(32.0, min(width, height) * .10)
                    and (point - pending.previous_event_position).length >= 8.0)
        previous = pending.cursor_candidate
        stable = (eligible and previous is not None
                  and (point - previous).length <= .25
                  and read_at - pending.cursor_candidate_at >= REBASE_CURSOR_POLL)
        self._trace_control("edge_rebase_cursor_sample", "read_after_sentinel", True,
            to_position=point, details={"readStartedAt": started, "readFinishedAt": read_at,
                "eligible": eligible, "stable": stable, "poll": pending.cursor_polls,
                "arithmeticOrigin": self._vec_dict(center)})
        if stable:
            pending.rebase_point = point
            pending.candidate = candidate
            pending.origin_method = "observed_stable_cursor"
            self._trace_control("edge_rebase_origin_adopted", "stable_cursor_without_warp", True,
                from_position=center, to_position=point,
                logical_position=self._last_logical_position,
                details={"readStartedAt": started, "readFinishedAt": read_at,
                         "cursorPolls": pending.cursor_polls})
            return "adopted"
        pending.cursor_candidate = point if eligible else None
        pending.cursor_candidate_at = read_at if eligible else None
        deadline = pending.sentinel_at + REBASE_CURSOR_TIMEOUT
        if max(now, read_at) >= deadline:
            pending.origin_method = "fallback_cursor_timeout"
            self._trace_control("edge_rebase_origin_fallback", "cursor_not_confirmed", True,
                to_position=center, details={"lastRead": self._vec_dict(point),
                "cursorPolls": pending.cursor_polls, "timeoutMs": REBASE_CURSOR_TIMEOUT * 1000})
            return "fallback"
        pending.next_deadline = min(deadline, read_at + REBASE_CURSOR_POLL)
        return "wait"

    def request_stop(self, reason: str = "cancel") -> None:
        """Close the admission gate without waiting for the motion lock."""

        reason = str(reason or "cancel")
        with self._lifecycle:
            if not self._release_requested.is_set():
                self._cancel_epoch += 1
                self._release_reason = reason
                self._release_requested.set()
            self._close_requested = True
            self._lifecycle.notify_all()

    def down(self, position: Vec2, _timestamp: float) -> None:
        with self._lock:
            if self._release_requested.is_set():
                return
            if self._session_pending or self._down:
                return
            # A later burst starts on the model's newly predicted handle. This
            # is the DOWN point; subsequent DRAG locations are allowed to move.
            if not self._point_is_safe(position):
                raise RuntimeError("gesture anchor is outside safe display bounds")
            self._anchor = position
            self._model_position = position
            self._mapping_logical_anchor = position
            self._mapping_event_anchor = position
            self._orbit_safe_press = None
            self._burst_rebase_count = 0
            self._location_scale_status["anchor"] = self._vec_dict(position)
            self._last_logical_position = self._anchor
            self._last_event_position = self._anchor
            self._session_pending = True

    def drag(self, position: Vec2, _timestamp: float) -> None:
        with self._lock:
            if self._release_requested.is_set():
                return
            if not self._session_pending and not self._down:
                raise RuntimeError("cannot drag without owning a left-button down")
            if self._model_position is None:
                raise RuntimeError("relative drag has no model origin")
            self._drag_absolute_unlocked(position)

    def drag_frame(self, frame: "MotionFrame") -> None:
        """Move the event location along the logical wheel-handle path."""

        with self._lock:
            if self._release_requested.is_set():
                return
            if not self._session_pending and not self._down:
                raise RuntimeError("cannot drag without owning a left-button down")
            before = frame.logical_before
            after = frame.logical_after
            mode = str(frame.mode)
            if mode not in ("orbit", "push_pull"):
                raise ValueError("unsupported motion frame mode: %s" % mode)
            logical = {
                "mode": mode,
                "before": (float(before.x), float(before.y)),
                "after": (float(after.x), float(after.y)),
                "applied": float(frame.logical_applied),
                "purpose": frame.purpose,
                "timestamp": float(frame.timestamp),
                "clamped": bool(frame.clamped),
                "crossedCenter": bool(frame.crossed_center),
                "anchor": (float(self._anchor.x), float(self._anchor.y)),
                "locationScale": self._location_scale,
                "deltaScale": LOGICAL_DELTA_SCALE,
                "relativeDeltaSpace": "zeroed_event_fields",
            }
            self._drag_absolute_unlocked(
                after,
                logical=logical,
                safe_press_mode=mode,
            )

    def observe_motion_frame(self, frame: "MotionFrame") -> None:
        """Expose a logical clamp without posting a CoreGraphics event.

        The engine uses this only when a radial frame is clamped with exactly
        zero displacement.  Feedback still needs that fact to request an
        outer-limit confirmation, but synthesizing DOWN/DRAG/UP here would be
        a click that Resolve can interpret as a reset.
        """

        with self._lock:
            mode = str(frame.mode)
            if mode not in ("orbit", "push_pull"):
                raise ValueError("unsupported motion frame mode: %s" % mode)
            before = frame.logical_before
            after = frame.logical_after
            logical = {
                "mode": mode,
                "before": (float(before.x), float(before.y)),
                "after": (float(after.x), float(after.y)),
                "applied": float(frame.logical_applied),
                "timestamp": float(frame.timestamp),
                "clamped": bool(frame.clamped),
                "crossedCenter": bool(frame.crossed_center),
                "locationScale": self._location_scale,
                "deltaScale": LOGICAL_DELTA_SCALE,
                "relativeDeltaSpace": "zeroed_event_fields",
            }
            if self._anchor is not None:
                logical["anchor"] = (
                    float(self._anchor.x),
                    float(self._anchor.y),
                )
            self._trace_motion_observation(frame, logical)

    def drag_relative(self, delta: Vec2, _timestamp: float) -> None:
        """Advance the event location by one relative logical displacement."""

        with self._lock:
            if self._release_requested.is_set():
                return
            if not self._session_pending and not self._down:
                raise RuntimeError("cannot drag without owning a left-button down")
            origin = self._model_position
            if origin is None:
                raise RuntimeError("relative drag has no model origin")
            target = Vec2(origin.x + delta.x, origin.y + delta.y)
            self._drag_absolute_unlocked(target)

    def up(self, position: Vec2, _timestamp: float, reason: str = "idle") -> None:
        with self._lock:
            if self._release_requested.is_set():
                # A failsafe UP may already have completed while this logical
                # session was blocked in a native post.  Reconcile the model
                # side without creating another normal-path event.
                if not self._physical_down.is_set():
                    self._mark_released()
                    self._discard_pending_session()
                    return
                self.emergency_release(reason)
                if not self._physical_down.is_set():
                    self._mark_released()
                    self._discard_pending_session()
                return
            if not self._down:
                self._discard_pending_session()
                restore_error = self._restore_cursor_association(reason)
                if restore_error is not None:
                    raise restore_error
                return
            self._model_position = position
            release_position = self._last_event_position
            post_error = None
            try:
                # This path intentionally has no frontmost-app or permission gate:
                # once we own DOWN, releasing it is always the safest operation.
                self._post("up", release_position, reason)
            except Exception as exc:
                self._interlock.mark_cancel("mouse_up_post_failed:%s" % reason)
                post_error = exc
            else:
                self._mark_released()
            if post_error is not None:
                # The normal source failed; retry through the source reserved
                # exclusively for unconditional release. Never warp after a
                # failed normal UP.
                self.emergency_release("mouse_up_post_failed:%s" % reason)
                raise post_error
            association_error = self._restore_cursor_association(reason)
            if association_error is not None:
                raise association_error

    def emergency_release(self, reason: str = "emergency_release") -> bool:
        """Try an UP through the independent source without the motion RLock."""

        self.request_stop(reason)
        # Admission marks may-down before entering the native DOWN/DRAG.  Do
        # not first inspect logical ``_down``: it lives behind the very lock a
        # stuck motion post owns.
        if not self._physical_down.is_set():
            return self._restore_cursor_association(reason) is None
        released = False
        for _attempt in range(2):
            try:
                released = self._post_failsafe_up(reason)
            except Exception:
                released = False
            if released:
                break
        if not released:
            self._interlock.mark_cancel("emergency_release_failed:%s" % reason)
        restored = self._restore_cursor_association(reason) is None
        return released and restored

    def close(self, blocking: bool = True) -> bool:
        """Quiesce native calls, release DOWN, then release both sources.

        ``blocking=False`` performs only the safety phase.  A controller that
        times out waiting for its runner keeps the sink quarantined and calls
        this method again from its reaper after the runner has terminated.
        """

        self.request_stop("sink_close")
        released = self.emergency_release("sink_close")
        if not blocking:
            return released

        with self._lifecycle:
            while self._active_native_calls:
                self._lifecycle.wait()
            if self._closed:
                return released

        # There can no longer be a motion owner once all native calls and the
        # runner are quiescent.  A final recovery is cheap and prevents source
        # release while the OS might still consider the button held.
        if self._physical_down.is_set():
            released = self.emergency_release("sink_close_final") and released
        if not released or self._physical_down.is_set():
            return False

        with self._lock:
            self._mark_released()
            self._discard_pending_session()
            restored = self._restore_cursor_association("sink_close") is None

        with self._lifecycle:
            while self._active_native_calls:
                self._lifecycle.wait()
            if self._closed:
                return released and restored
            source = self._source
            failsafe_source = self._failsafe_source
            self._source = None
            self._failsafe_source = None
            self._closed = True
            self._lifecycle.notify_all()
        # CFRelease is intentionally outside all locks.
        if source is not None:
            self._bindings.release_mouse_source(source)
        if failsafe_source is not None:
            self._bindings.release_mouse_source(failsafe_source)
        return released and restored

    def _drag_absolute_unlocked(
        self,
        position: Vec2,
        logical: Optional[dict] = None,
        safe_press_mode: Optional[str] = None,
    ) -> None:
        if self._release_requested.is_set():
            return
        if self._pending_rebase is not None:
            raise RuntimeError("edge rebase transport is pending")
        if self._mapping_logical_anchor is None or self._mapping_event_anchor is None:
            raise RuntimeError("absolute drag has no mapping anchor")
        requested = Vec2(
            position.x - self._last_logical_position.x,
            position.y - self._last_logical_position.y,
        )
        relative = {
            "requested": (float(requested.x), float(requested.y)),
            "postedEventFields": (0, 0),
            "scaledLocationDelta": (
                float(requested.x * self._location_scale),
                float(requested.y * self._location_scale),
            ),
        }
        if requested.x == 0.0 and requested.y == 0.0:
            # The engine normally filters this case. Keep a direct-call guard
            # so a no-op can never turn into a DOWN/UP click lifecycle.
            event_position = self._event_position(position)
            self._trace_post(
                "drag_suppressed",
                (float(event_position.x), float(event_position.y)),
                self._clock(),
                "zero_absolute_delta",
                True,
                relative_delta=relative,
                logical=logical,
            )
            return
        if safe_press_mode is not None:
            orbit_safe_press = self._apply_outer_safe_press_unlocked(
                safe_press_mode
            )
            if orbit_safe_press is not None and logical is not None:
                logical["orbitSafePress"] = self._copy_orbit_safe_press(
                    orbit_safe_press
                )
        event_position = self._event_position(position)
        needs_rebase = self._point_requires_rebase(event_position)
        try:
            rebase_plan = (
                self._prepare_rebase(requested) if needs_rebase else None
            )
        except Exception:
            self._interlock.mark_cancel("mouse_drag_post_failed")
            self.emergency_release("mouse_drag_post_failed")
            raise
        # All deterministic rebase checks happen before the deferred DOWN. A
        # bad topology or oversized first frame therefore cannot degrade into
        # a click-only DOWN/UP pair on the colour control. Keep DOWN outside the
        # post catch because its own failure path already performs recovery.
        if not self._down:
            if not self._begin_physical_down_unlocked(self._last_event_position):
                return
        try:
            if rebase_plan is not None:
                admitted = self._stage_rebase_while_down_unlocked(
                    position,
                    requested,
                    rebase_plan=rebase_plan,
                    relative_delta=relative,
                    logical=logical,
                )
            else:
                if not self._point_is_safe(event_position):
                    raise RuntimeError(
                        "scaled mouse location is outside safe bounds"
                    )
                admitted = self._post(
                    "drag",
                    event_position,
                    "gesture_update",
                    relative_delta=relative,
                    logical=logical,
                )
            if not admitted:
                # False can mean either "not admitted" or "posted late and
                # tail UP attempted".  A failed tail deliberately leaves the
                # conservative physical marker set so close/reaper can retry;
                # never erase that evidence here.
                if not self._physical_down.is_set():
                    self._mark_released()
                    self._discard_pending_session()
                return
            if rebase_plan is not None:
                # Sentinel is a transport boundary, not a committed motion
                # endpoint. The staged phase owner updates all mapping state
                # only after the neutral anchors and separate motion succeed.
                return
            self._last_logical_position = position
            self._last_event_position = event_position
            self._model_position = position
        except Exception:
            self._interlock.mark_cancel("mouse_drag_post_failed")
            self.emergency_release("mouse_drag_post_failed")
            raise

    def _event_position(self, position: Vec2) -> Vec2:
        """Map a predicted handle point within the current physical segment."""

        logical_anchor = self._mapping_logical_anchor
        event_anchor = self._mapping_event_anchor
        if logical_anchor is None or event_anchor is None:
            raise RuntimeError("mouse mapping anchor is unavailable")
        return Vec2(
            event_anchor.x
            + (position.x - logical_anchor.x) * self._location_scale,
            event_anchor.y
            + (position.y - logical_anchor.y) * self._location_scale,
        )

    def _apply_outer_safe_press_unlocked(self, mode: str) -> Optional[dict]:
        """Inset only the first physical DOWN of an outer-rim drag burst.

        Resolve can ignore an orbit or push/pull which begins directly on the
        visual rim.  ``orbitSafePress`` remains the public telemetry key for
        compatibility with existing traces and log tooling.
        The mapping deliberately remains split: ``_mapping_logical_anchor``
        and all model positions stay on the detected white point, while only
        ``_mapping_event_anchor``/``_last_event_position`` move inward.  The
        ordinary absolute mapping therefore applies every later logical delta
        from the safe physical landing without accumulating a model offset.
        """

        if (
            mode not in ("orbit", "push_pull")
            or self._down
            or not self._session_pending
            or self._logical_bounds is None
        ):
            return None
        if self._orbit_safe_press is not None:
            return self._orbit_safe_press
        logical_anchor = self._mapping_logical_anchor
        if logical_anchor is None:
            raise RuntimeError("outer safe press has no logical mapping anchor")

        left, top, width, height = self._logical_bounds
        center = Vec2(left + width / 2.0, top + height / 2.0)
        visual_radius = min(width, height) / 2.0
        offset = logical_anchor - center
        logical_radius = offset.length
        if (
            visual_radius <= 0.0
            or logical_radius
            < visual_radius * ORBIT_SAFE_PRESS_START_RATIO
        ):
            return None

        applied_inset = min(ORBIT_SAFE_PRESS_INSET_PX, logical_radius)
        physical_down = logical_anchor - offset.normalized() * applied_inset
        if not self._point_is_safe(physical_down):
            raise RuntimeError("outer safe press is outside safe display bounds")

        # Do not touch the logical anchor, last logical position, model
        # position, or public anchor.  Only the event-space origin changes.
        self._mapping_event_anchor = physical_down
        self._last_event_position = physical_down
        self._orbit_safe_press = {
            "applied": True,
            "mode": mode,
            "strategy": "radial_inset_first_physical_down",
            "thresholdRatio": ORBIT_SAFE_PRESS_START_RATIO,
            "visualRadiusPx": visual_radius,
            "logicalRadiusPx": logical_radius,
            "requestedInsetPx": ORBIT_SAFE_PRESS_INSET_PX,
            "appliedInsetPx": applied_inset,
            "logicalAnchor": self._vec_dict(logical_anchor),
            "physicalDown": self._vec_dict(physical_down),
        }
        return self._orbit_safe_press

    def _stage_rebase_while_down_unlocked(
        self,
        position: Vec2,
        requested: Vec2,
        *,
        rebase_plan: Optional[Tuple[Vec2, Vec2]] = None,
        relative_delta: Optional[dict] = None,
        logical: Optional[dict] = None,
    ) -> bool:
        """Post the sentinel and stage the remaining transport.

        The warp, neutral anchors and pending motion are not performed here.
        ``service_transport`` advances them at their measured deadlines while
        retaining one physical DOWN and leaving normal logical input queued.
        """

        if not self._down or not self._physical_down.is_set():
            raise RuntimeError("edge rebase requires an active left-button down")
        if self._pending_rebase is not None:
            raise RuntimeError("edge rebase transport is already pending")
        if rebase_plan is None:
            rebase_point, candidate = self._prepare_rebase(requested)
        else:
            rebase_point, candidate = rebase_plan
        previous_event_position = self._last_event_position

        sentinel_timing = self._post_rebase_sentinel(
            self._event_position(position)
        )
        if sentinel_timing is None:
            return False
        sentinel_posted_at, sentinel_at = sentinel_timing
        self._pending_rebase = _PendingRebase(
            phase="wait_warp",
            sentinel_posted_at=sentinel_posted_at,
            sentinel_at=sentinel_at,
            next_deadline=sentinel_at + REBASE_WARP_DELAY,
            rebase_point=rebase_point,
            candidate=candidate,
            logical_position=position,
            requested=requested,
            previous_event_position=previous_event_position,
            relative_delta=relative_delta,
            logical=logical,
        )
        self._trace_control(
            "edge_rebase_staged",
            "edge_threshold",
            True,
            from_position=previous_event_position,
            to_position=candidate,
            logical_position=position,
            details={
                "phase": "wait_warp",
                "sentinelAt": sentinel_posted_at,
                "sentinelCompletedAt": sentinel_at,
                "nextDeadline": sentinel_at + REBASE_WARP_DELAY,
            },
        )
        return True

    def _prepare_rebase(self, requested: Vec2) -> Tuple[Vec2, Vec2]:
        """Validate all deterministic transport endpoints before side effects."""

        rebase_bounds = self._rebase_bounds
        if rebase_bounds is None:
            raise RuntimeError("edge rebase requires display bounds")
        left, top, width, height = rebase_bounds
        rebase_point = Vec2(left + width / 2.0, top + height / 2.0)
        candidate = Vec2(
            rebase_point.x + requested.x * self._location_scale,
            rebase_point.y + requested.y * self._location_scale,
        )
        if (
            not self._point_is_rebase_safe(rebase_point)
            or not self._point_is_rebase_safe(candidate)
        ):
            raise RuntimeError("scaled step exceeds safe bounds after edge rebase")
        self._validate_sentinel_display_topology()
        return rebase_point, candidate

    @staticmethod
    def _normalize_bounds(
        bounds: Optional[Tuple[float, float, float, float]]
    ) -> Optional[Tuple[float, float, float, float]]:
        if bounds is None:
            return None
        try:
            values = tuple(float(value) for value in bounds)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "bounds must contain four finite numbers"
            ) from exc
        if (
            len(values) != 4
            or not all(math.isfinite(value) for value in values)
            or values[2] <= 0.0
            or values[3] <= 0.0
        ):
            raise ValueError("bounds must be a finite positive rectangle")
        return values

    @staticmethod
    def _inset_bounds(
        bounds: Optional[Tuple[float, float, float, float]], margin: float
    ) -> Optional[Tuple[float, float, float, float]]:
        if bounds is None:
            return None
        left, top, width, height = bounds
        safe_width = width - 2.0 * margin
        safe_height = height - 2.0 * margin
        if safe_width <= 0.0 or safe_height <= 0.0:
            raise ValueError("edge_margin leaves no safe display rectangle")
        return (left + margin, top + margin, safe_width, safe_height)

    @staticmethod
    def _rect_dict(
        bounds: Optional[Tuple[float, float, float, float]]
    ) -> Optional[dict]:
        if bounds is None:
            return None
        return {
            "x": bounds[0],
            "y": bounds[1],
            "width": bounds[2],
            "height": bounds[3],
        }

    @staticmethod
    def _vec_dict(position: Optional[Vec2]) -> Optional[dict]:
        if position is None:
            return None
        return {"x": float(position.x), "y": float(position.y)}

    def _point_is_safe(self, position: Vec2) -> bool:
        bounds = self._safe_bounds
        if bounds is None:
            return True
        left, top, width, height = bounds
        return (
            left <= position.x <= left + width
            and top <= position.y <= top + height
        )

    def _point_tuple_is_safe(self, position: Tuple[float, float]) -> bool:
        return self._point_is_safe(Vec2(float(position[0]), float(position[1])))

    def _point_is_rebase_safe(self, position: Vec2) -> bool:
        bounds = self._rebase_bounds
        if bounds is None:
            return True
        left, top, width, height = bounds
        return (
            left <= position.x <= left + width
            and top <= position.y <= top + height
        )

    def _point_requires_rebase(self, position: Vec2) -> bool:
        return self._rebase_bounds is not None and not self._point_is_rebase_safe(
            position
        )

    @classmethod
    def calculate_location_scale(
        cls,
        requested_scale: float,
        anchor: Vec2,
        display_bounds: Tuple[float, float, float, float],
        logical_bounds: Tuple[float, float, float, float],
        edge_margin: float = DEFAULT_EDGE_MARGIN,
    ) -> dict:
        """Validate geometry while preserving the requested scale exactly."""

        requested = float(requested_scale)
        margin = float(edge_margin)
        if not math.isfinite(requested) or requested <= 0.0:
            raise ValueError("requested_scale must be finite and greater than zero")
        if not math.isfinite(margin) or margin < 0.0:
            raise ValueError("edge_margin must be finite and non-negative")
        display = cls._normalize_bounds(display_bounds)
        wheel = cls._normalize_bounds(logical_bounds)
        assert display is not None and wheel is not None
        safe = cls._inset_bounds(display, POST_EDGE_MARGIN)
        rebase = cls._inset_bounds(display, margin)
        assert safe is not None
        if not isinstance(anchor, Vec2) or not all(
            math.isfinite(value) for value in (anchor.x, anchor.y)
        ):
            raise ValueError("anchor must be a finite Vec2")

        wheel_left, wheel_top, wheel_width, wheel_height = wheel
        wheel_right = wheel_left + wheel_width
        wheel_bottom = wheel_top + wheel_height
        safe_left, safe_top, safe_width, safe_height = safe
        safe_right = safe_left + safe_width
        safe_bottom = safe_top + safe_height
        if not (
            wheel_left <= anchor.x <= wheel_right
            and wheel_top <= anchor.y <= wheel_bottom
        ):
            raise ValueError("anchor is outside the logical wheel bounds")
        if not (
            safe_left <= anchor.x <= safe_right
            and safe_top <= anchor.y <= safe_bottom
        ):
            raise ValueError("anchor is outside the safe display bounds")

        if not (
            safe_left <= wheel_left
            and wheel_right <= safe_right
            and safe_top <= wheel_top
            and wheel_bottom <= safe_bottom
        ):
            raise ValueError("logical wheel bounds are outside the safe display")
        return {
            "enabled": True,
            "resolved": True,
            "requested": requested,
            "effective": requested,
            "attenuated": False,
            "strategy": "fixed_scale_timed_tourbox_rebase",
            "edgeMargin": margin,
            "postEdgeMargin": POST_EDGE_MARGIN,
            "rebaseWhileDown": True,
            "rebaseTarget": "safe_display_center",
            "rebaseTransport": (
                "timed_sentinel_warp_neutral_anchors_then_motion"
            ),
            "rebaseWarpDelayMs": REBASE_WARP_DELAY * 1000.0,
            "rebaseAnchorDelayMs": REBASE_ANCHOR_DELAY * 1000.0,
            "rebaseMinAnchorAfterWarpMs": (
                REBASE_MIN_ANCHOR_AFTER_WARP * 1000.0
            ),
            "outOfBoundsDragEvents": True,
            "outOfBoundsDragScope": "fixed_-10000_sentinel_only",
            "hostReanchorSemantics": (
                "tourbox_timing_matched_requires_davinci_validation"
            ),
            "restoreAfterIdleUp": "transport_endpoint",
            "anchor": {"x": float(anchor.x), "y": float(anchor.y)},
            "displayBounds": cls._rect_dict(display),
            "safeBounds": cls._rect_dict(safe),
            "rebaseBounds": cls._rect_dict(rebase),
            "wheelBounds": cls._rect_dict(wheel),
        }

    def _resolve_location_scale(self, anchor: Optional[Vec2]) -> dict:
        if self._display_bounds is None:
            return {
                "enabled": False,
                "resolved": anchor is not None,
                "requested": self._requested_location_scale,
                "effective": self._requested_location_scale,
                "attenuated": False,
                "strategy": "fixed_scale_timed_tourbox_rebase",
                "edgeMargin": self._edge_margin,
                "postEdgeMargin": POST_EDGE_MARGIN,
                "rebaseWhileDown": False,
                "rebaseTarget": None,
                "rebaseTransport": None,
                "rebaseWarpDelayMs": REBASE_WARP_DELAY * 1000.0,
                "rebaseAnchorDelayMs": REBASE_ANCHOR_DELAY * 1000.0,
                "rebaseMinAnchorAfterWarpMs": (
                    REBASE_MIN_ANCHOR_AFTER_WARP * 1000.0
                ),
                "outOfBoundsDragEvents": False,
                "outOfBoundsDragScope": None,
                "hostReanchorSemantics": "not_applicable",
                "restoreAfterIdleUp": None,
                "anchor": (
                    None
                    if anchor is None
                    else {"x": float(anchor.x), "y": float(anchor.y)}
                ),
                "displayBounds": None,
                "safeBounds": None,
                "rebaseBounds": None,
                "wheelBounds": None,
            }
        if anchor is None:
            raise ValueError(
                "initial_anchor is required when display safety is enabled"
            )
        assert self._logical_bounds is not None
        return self.calculate_location_scale(
            self._requested_location_scale,
            anchor,
            self._display_bounds,
            self._logical_bounds,
            self._edge_margin,
        )

    @staticmethod
    def _copy_scale_status(status: dict) -> dict:
        result = dict(status)
        for key in (
            "anchor",
            "displayBounds",
            "safeBounds",
            "rebaseBounds",
            "wheelBounds",
            "mappingLogicalAnchor",
            "mappingEventAnchor",
        ):
            value = result.get(key)
            if isinstance(value, dict):
                result[key] = dict(value)
        return result

    @staticmethod
    def _copy_orbit_safe_press(status: Optional[dict]) -> Optional[dict]:
        if status is None:
            return None
        result = dict(status)
        for key in ("logicalAnchor", "physicalDown"):
            value = result.get(key)
            if isinstance(value, dict):
                result[key] = dict(value)
        return result

    def _begin_physical_down_unlocked(
        self,
        anchor: Vec2,
    ) -> bool:
        if self._release_requested.is_set():
            return False
        self._down = True
        self._interlock.set_owner_down(True)
        self._state_callback(True)
        posted = False
        try:
            self._last_event_position = anchor
            posted = self._post("down", anchor, "gesture_start")
            if not posted:
                if not self._physical_down.is_set():
                    self._mark_released()
                    self._discard_pending_session()
                return False
            if self._detach_cursor and not self._cursor_detached:
                self._set_cursor_associated(False)
        except Exception:
            reason = (
                "mouse_cursor_disassociate_failed"
                if posted else "mouse_down_post_failed"
            )
            self._interlock.mark_cancel(reason)
            self.emergency_release(reason)
            raise
        return True

    def _set_cursor_associated(self, connected: bool) -> None:
        setter = getattr(self._bindings, "associate_mouse_and_cursor", None)
        if setter is not None:
            setter(bool(connected))
        self._cursor_detached = not connected

    def _restore_cursor_association(self, reason: str) -> Optional[Exception]:
        if not self._detach_cursor and not self._cursor_detached:
            return None
        try:
            self._set_cursor_associated(True)
        except Exception as exc:
            self._interlock.mark_cancel(
                "mouse_cursor_reassociate_failed:%s" % reason
            )
            return exc
        return None

    def _warp_cursor(self, position: Vec2, reason: str) -> bool:
        """Perform one coordinated, non-event cursor warp."""

        if not self._point_is_safe(position):
            raise RuntimeError("refusing to warp mouse outside safe bounds")
        point = (float(position.x), float(position.y))
        timestamp = self._clock()
        with self._lifecycle:
            if self._closed or self._release_requested.is_set():
                return False
            epoch = self._cancel_epoch
            self._active_native_calls += 1
            self._last_event_at = timestamp
        error: Optional[Exception] = None
        warp_echo_token: Optional[int] = None
        try:
            warp = getattr(self._bindings, "warp_mouse_cursor", None)
            if not callable(warp):
                raise RuntimeError("cursor warp binding is unavailable")
            # A CG warp is not a posted event and must not create a pending
            # confirmation.  Its untagged zero-delta callback can arrive after
            # the tagged anchor has already replaced `_expected`, so retain one
            # exact, short-lived echo ticket across those tagged events.
            warp_echo_token = self._interlock.note_controlled_warp(
                point, timestamp
            )
            self._interlock.expect(point)
            warp(point)
        except Exception as exc:
            if warp_echo_token is not None:
                self._interlock.cancel_controlled_warp(warp_echo_token)
            error = exc
            self._trace_control(
                reason, reason, False, to_position=position, error=str(exc)
            )
        else:
            self._trace_control(reason, reason, True, to_position=position)
        finally:
            with self._lifecycle:
                cancelled = (
                    self._release_requested.is_set()
                    or self._cancel_epoch != epoch
                )
                self._active_native_calls -= 1
                self._lifecycle.notify_all()
        if error is not None:
            raise error
        if cancelled and warp_echo_token is not None:
            self._interlock.cancel_controlled_warp(warp_echo_token)
        return not cancelled

    def _post(
        self,
        kind: str,
        position: Vec2,
        reason: str,
        relative_delta: Optional[dict] = None,
        logical: Optional[dict] = None,
        trace_kind: Optional[str] = None,
        *,
        stationary_down: bool = False,
    ) -> bool:
        """Post an ordinary event whose location is inside safe bounds."""

        return self._post_event(
            kind,
            position,
            reason,
            relative_delta=relative_delta,
            logical=logical,
            trace_kind=trace_kind,
            **({"stationary_down": True} if stationary_down else {}),
        )

    def _post_rebase_sentinel(
        self, trigger_position: Vec2
    ) -> Optional[Tuple[float, float]]:
        """Post the sole permitted off-screen transport marker.

        This cannot be generalized to other coordinates or event kinds.  In
        particular it preserves the previous safe failsafe endpoint so every
        cancellation path can still release the button on screen.
        """

        if (
            not self._down
            or not self._physical_down.is_set()
            or self._display_bounds is None
            or not self._point_requires_rebase(trigger_position)
        ):
            raise RuntimeError(
                "edge rebase sentinel requires an active threshold crossing"
            )
        # Re-read immediately before posting as a fail-closed hot-plug guard;
        # `_prepare_rebase` already performed the same check before a possible
        # first DOWN.
        self._validate_sentinel_display_topology()
        posted = self._post_event(
            "drag",
            REBASE_SENTINEL,
            "edge_rebase_sentinel",
            trace_kind="edge_rebase_sentinel",
            rebase_sentinel=True,
        )
        if not posted:
            return None
        # The host post is synchronous, so all phase delays are measured from
        # its successful return. A slow post must never consume the intended
        # sentinel-to-warp gap before the runner regains control.
        return (self.last_event_at, self._clock())

    def _validate_sentinel_display_topology(self) -> None:
        """Ensure the transport sentinel is outside every current display."""

        display_resolver = getattr(self._bindings, "active_display_bounds", None)
        if not callable(display_resolver):
            raise RuntimeError(
                "cannot verify edge rebase sentinel against active displays"
            )
        displays = tuple(
            self._normalize_bounds(bounds) for bounds in display_resolver()
        )
        if not displays or any(bounds is None for bounds in displays):
            raise RuntimeError("active display topology is unavailable")
        assert self._display_bounds is not None
        if self._display_bounds not in displays:
            raise RuntimeError("active display topology changed during gesture")
        sentinel_point = (REBASE_SENTINEL.x, REBASE_SENTINEL.y)
        if any(
            self._point_in_bounds(sentinel_point, bounds)
            for bounds in displays
            if bounds is not None
        ):
            raise RuntimeError("edge rebase sentinel intersects an active display")

    @staticmethod
    def _point_in_bounds(
        point: Tuple[float, float],
        bounds: Tuple[float, float, float, float],
    ) -> bool:
        left, top, width, height = bounds
        return (
            left <= point[0] <= left + width
            and top <= point[1] <= top + height
        )

    def _post_event(
        self,
        kind: str,
        position: Vec2,
        reason: str,
        relative_delta: Optional[dict] = None,
        logical: Optional[dict] = None,
        trace_kind: Optional[str] = None,
        *,
        rebase_sentinel: bool = False,
        stationary_down: bool = False,
    ) -> bool:
        if stationary_down and kind != "down":
            raise ValueError("stationary_down requires a DOWN event")
        point = (float(position.x), float(position.y))
        is_exact_sentinel = (
            kind == "drag"
            and point == (REBASE_SENTINEL.x, REBASE_SENTINEL.y)
            and self._down
            and self._physical_down.is_set()
            and self._display_bounds is not None
        )
        if rebase_sentinel and not is_exact_sentinel:
            raise RuntimeError("invalid edge rebase sentinel event")
        if not self._point_tuple_is_safe(point) and not (
            rebase_sentinel and is_exact_sentinel
        ):
            raise RuntimeError("refusing to post mouse event outside safe bounds")
        recorded_kind = str(trace_kind or kind)
        timestamp = self._clock()
        is_button_motion = kind in ("down", "drag")
        is_cancelable_motion = kind in ("down", "drag", "move")
        with self._lifecycle:
            if self._closed:
                if is_cancelable_motion:
                    return False
                raise RuntimeError("mouse event sources are closed")
            if is_cancelable_motion and self._release_requested.is_set():
                return False
            source = self._source
            if source is None:
                raise RuntimeError("mouse event source is closed")
            epoch = self._cancel_epoch
            self._active_native_calls += 1
            if is_button_motion:
                self._active_motion_calls += 1
                self._physical_down.set()
                if not rebase_sentinel:
                    self._failsafe_position = point
            self._last_event_at = timestamp

        error: Optional[Exception] = None
        try:
            self._interlock.expect(point)
            self._interlock.note_posted(timestamp, kind, point)
            targeted_poster = getattr(
                self._bindings, "post_left_mouse_to_pid", None
            )
            if stationary_down:
                stationary_poster = getattr(self._bindings, "post_left_mouse_stationary_down", None)
                if not callable(stationary_poster):
                    raise RuntimeError("stationary DOWN posting is unavailable")
                stationary_poster(source, point, self._interlock.tag)
            elif self._target_pid is not None:
                if not callable(targeted_poster):
                    raise RuntimeError("target-process mouse posting is unavailable")
                targeted_poster(
                    source,
                    self._target_pid,
                    kind,
                    point,
                    self._interlock.tag,
                )
            else:
                self._bindings.post_left_mouse(
                    source, kind, point, self._interlock.tag
                )
        except Exception as exc:
            error = exc
            self._trace_post(
                recorded_kind,
                point,
                timestamp,
                reason,
                False,
                str(exc),
                relative_delta,
                logical,
                posted_kind=kind,
            )
        else:
            self._trace_post(
                recorded_kind, point, timestamp, reason, True,
                relative_delta=relative_delta,
                logical=logical,
                posted_kind=kind,
            )

        # A native DOWN/DRAG which was admitted before cancellation cannot be
        # withdrawn.  If it returns late, append an UP through the independent
        # source before allowing the runner to leave this frame.
        tail_ok = False
        cancelled_while_posting = False
        if is_cancelable_motion:
            with self._lifecycle:
                cancelled_while_posting = (
                    self._release_requested.is_set()
                    or self._cancel_epoch != epoch
                )
            if cancelled_while_posting and is_button_motion:
                try:
                    tail_ok = self._post_failsafe_up(
                        "late_%s_after_cancel" % kind
                    )
                except Exception:
                    tail_ok = False

        if error is not None and is_button_motion and not cancelled_while_posting:
            # A synchronous failure did not establish the requested endpoint;
            # preserve the last confirmed event location for recovery.  A
            # blocked call cancelled from another thread keeps its admitted
            # endpoint instead and receives a tail UP there.
            with self._lifecycle:
                self._failsafe_position = (
                    float(self._last_event_position.x),
                    float(self._last_event_position.y),
                )

        with self._lifecycle:
            if is_button_motion:
                self._active_motion_calls -= 1
                if tail_ok and self._active_motion_calls == 0:
                    self._physical_down.clear()
            self._active_native_calls -= 1
            self._lifecycle.notify_all()

        if error is not None:
            raise error
        return not cancelled_while_posting

    def _post_failsafe_up(self, reason: str) -> bool:
        """Post UP with a leased source, never taking the motion RLock."""

        point = self._failsafe_position
        if not self._point_tuple_is_safe(point):
            raise RuntimeError("refusing to release mouse outside safe bounds")
        timestamp = self._clock()
        with self._lifecycle:
            if self._closed:
                return not self._physical_down.is_set()
            source = self._failsafe_source
            if source is None:
                raise RuntimeError("failsafe mouse event source is closed")
            self._active_native_calls += 1
            self._last_event_at = timestamp
        try:
            self._interlock.expect(point)
            self._interlock.note_posted(timestamp, "up", point)
            targeted_poster = getattr(
                self._bindings, "post_left_mouse_to_pid", None
            )
            if self._target_pid is not None:
                if not callable(targeted_poster):
                    raise RuntimeError("target-process mouse posting is unavailable")
                targeted_poster(
                    source,
                    self._target_pid,
                    "up",
                    point,
                    self._interlock.tag,
                )
            else:
                self._bindings.post_left_mouse(
                    source, "up", point, self._interlock.tag
                )
        except Exception as exc:
            self._trace_post(
                "up", point, timestamp, reason, False, str(exc)
            )
            raise
        else:
            self._trace_post("up", point, timestamp, reason, True)
            with self._lifecycle:
                if self._active_motion_calls == 0:
                    self._physical_down.clear()
            self._interlock.set_owner_down(False)
            try:
                self._state_callback(False)
            except Exception:
                pass
            return True
        finally:
            with self._lifecycle:
                self._active_native_calls -= 1
                self._lifecycle.notify_all()

    def _trace_control(
        self,
        kind: str,
        reason: str,
        ok: bool,
        *,
        from_position: Optional[Vec2] = None,
        to_position: Optional[Vec2] = None,
        logical_position: Optional[Vec2] = None,
        error: str = "",
        details: Optional[dict] = None,
    ) -> None:
        """Record a mapping/warp operation which is not a posted mouse event."""

        if self._trace_callback is None:
            return
        event = {
            "kind": kind,
            "monotonic": self._clock(),
            "reason": reason,
            "ok": bool(ok),
            "postedMouseEvent": False,
            "locationScale": self._location_scale_status_unlocked(),
        }
        if from_position is not None:
            event["fromPosition"] = self._vec_dict(from_position)
        if to_position is not None:
            event["toPosition"] = self._vec_dict(to_position)
        if logical_position is not None:
            event["logicalPosition"] = self._vec_dict(logical_position)
        if error:
            event["error"] = error
        if details is not None:
            event["details"] = dict(details)
        try:
            self._trace_callback(event)
        except Exception:
            pass

    def _trace_motion_observation(
        self,
        frame: "MotionFrame",
        logical: dict,
    ) -> None:
        """Record logical feedback metadata that was not sent to the host."""

        if self._trace_callback is None:
            return
        event = {
            "kind": "motion_observed",
            "position": self._vec_dict(frame.logical_after),
            "monotonic": float(frame.timestamp),
            "reason": "clamped_zero_displacement",
            "ok": True,
            "postedMouseEvent": False,
            "locationScale": self._location_scale_status_unlocked(),
            "logical": {
                **logical,
                "before": {
                    "x": logical["before"][0], "y": logical["before"][1]
                },
                "after": {
                    "x": logical["after"][0], "y": logical["after"][1]
                },
            },
        }
        anchor = logical.get("anchor")
        if anchor is not None:
            event["logical"]["anchor"] = {
                "x": anchor[0], "y": anchor[1]
            }
        try:
            self._trace_callback(event)
        except Exception:
            pass

    def _trace_post(
        self,
        kind: str,
        point: tuple,
        timestamp: float,
        reason: str,
        ok: bool,
        error: str = "",
        relative_delta: Optional[dict] = None,
        logical: Optional[dict] = None,
        posted_kind: Optional[str] = None,
    ) -> None:
        """Send a small record to the controller's in-memory queue only.

        A successful record means the post call returned, not that Resolve
        accepted the gesture.  Tap confirmations are tracked separately.
        Diagnostic callback failures must never interrupt an UP attempt.
        """

        if self._trace_callback is None:
            return
        event = {
            "kind": kind,
            "position": {"x": point[0], "y": point[1]},
            "clickState": MacOSBindings.SINGLE_CLICK_STATE,
            "tag": self._interlock.tag,
            "monotonic": timestamp,
            "reason": reason,
            "ok": ok,
            "postedMouseEvent": True,
        }
        if posted_kind is not None and posted_kind != kind:
            event["postedEventKind"] = posted_kind
        if error:
            event["error"] = error
        # Emergency UP can run while the motion thread owns ``_lock`` inside
        # a blocked native DRAG. Diagnostics must stay lock-free here.
        event["locationScale"] = self._location_scale_status_unlocked()
        if relative_delta is not None:
            event["relativeDelta"] = {
                name: {"x": value[0], "y": value[1]}
                for name, value in relative_delta.items()
            }
        if logical is not None:
            event["logical"] = {
                **logical,
                "before": {
                    "x": logical["before"][0], "y": logical["before"][1]
                },
                "after": {
                    "x": logical["after"][0], "y": logical["after"][1]
                },
            }
            anchor = logical.get("anchor")
            if anchor is not None:
                event["logical"]["anchor"] = {
                    "x": anchor[0], "y": anchor[1]
                }
        try:
            self._trace_callback(event)
        except Exception:
            pass

    def _mark_released(self) -> None:
        self._pending_rebase = None
        self._down = False
        self._session_pending = False
        self._physical_down.clear()
        self._interlock.set_owner_down(False)
        self._state_callback(False)

    def _discard_pending_session(self) -> None:
        self._pending_rebase = None
        self._session_pending = False
        self._anchor = None
        self._model_position = None
        self._mapping_logical_anchor = None
        self._mapping_event_anchor = None
        self._orbit_safe_press = None
        self._last_logical_position = Vec2(0.0, 0.0)
        self._last_event_position = Vec2(0.0, 0.0)
