"""Formal-plugin adapter for the safety-tested smooth wheel runtime.

The formal plugin keeps ownership of target selection and visual recognition.
This module owns the native gesture session: one formal recognition at the
session boundary, lossless encoder admission, and one balanced synthetic mouse
button lifecycle shared by orbit and push/pull.
"""

from __future__ import annotations

import math
import os
import platform
from functools import partial
from threading import Lock, RLock, current_thread
import time
from typing import Callable, Optional

from ..area_target_helpers import area_key
from ..config import WHEEL_DIAMETER_CENTER_FEEDBACK_IGNORE_RADIUS
from .axis_continuity import DiameterContinuity
from .geometry import Vec2
from .macos import MacOSBindings
from .windows import WindowsBindings
from .session_runtime import Calibration, WheelWorkerController, WorkerError


FORMAL_SMOOTH_RUNTIME_VERSION = "1.2.8"
_ACTIVE_STATES = {"armed", "dragging"}
_SAFE_AUTONOMOUS_FINAL_REASONS = {
    "idle",
    "normal_completion",
    "visual_confirmed",
}
_STARTUP_CADENCE_GUARD_SECONDS = 0.12
_UNAVAILABLE_RETRY_SECONDS = 3.0
_TAGGED_RECOVERY_MAX_AGE_SECONDS = 0.35
_WINDOWS_IDLE_RECALIBRATION_REASON = "windows_idle_visual_recalibration"
_COOLDOWN_UNAVAILABLE_CODES = {
    "event_tap_failed",
    "live_preflight_failed",
    "platform_unavailable",
}


class SmoothWheelUnavailable(RuntimeError):
    """Smooth startup failed cleanly before taking mouse ownership."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = str(code or "smooth_unavailable")


def _clean_shutdown_result(result):
    if isinstance(result, bool):
        return result
    if not isinstance(result, dict):
        return False
    return bool(
        not result.get("cleanupPending", False)
        and result.get("state", "disarmed") == "disarmed"
        and result.get("releaseOk", True) is not False
    )


def _finite_float(value, default=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _persisted_diameter_state(source, center, point):
    """Read an exact logical diameter only when it matches fresh geometry."""

    if not isinstance(source, dict):
        return None
    axis_angle = _finite_float(source.get("radial_axis_angle"))
    signed_radius = _finite_float(source.get("signed_radius"))
    if axis_angle is None or signed_radius is None:
        return None
    axis = Vec2(math.cos(axis_angle), math.sin(axis_angle)).normalized()
    visible_radius = (point - center).length
    near_center = (
        visible_radius < WHEEL_DIAMETER_CENTER_FEEDBACK_IGNORE_RADIUS
    )
    if near_center:
        # The component's direction is ambiguous, so compare its coordinate
        # with the exact logical prediction instead of comparing polar axes.
        # This preserves real sub-threshold motion but rejects stale state.
        if (center + axis * signed_radius - point).length > 2.0:
            return None
    elif (center + axis * signed_radius - point).length > 2.0:
        return None

    last_side = source.get("diameter_last_side")
    try:
        last_side = int(last_side)
    except (TypeError, ValueError):
        last_side = None
    if last_side not in (-1, 0, 1):
        last_side = 1 if signed_radius > 0.0 else -1 if signed_radius < 0.0 else 0

    last_x = _finite_float(source.get("last_nonzero_axis_x"))
    last_y = _finite_float(source.get("last_nonzero_axis_y"))
    if (
        last_x is not None
        and last_y is not None
        and math.hypot(last_x, last_y) > 1e-6
    ):
        last_axis = Vec2(last_x, last_y).normalized()
    elif abs(signed_radius) > 1e-6:
        last_axis = axis if signed_radius > 0.0 else axis * -1.0
    else:
        last_axis = axis if last_side >= 0 else axis * -1.0
    if near_center:
        return axis, signed_radius, last_side, last_axis
    if visible_radius > 1e-6:
        visible_axis = (point - center).normalized()
        if last_axis.dot(visible_axis) < 0.99:
            return None

        # The screenshot is authoritative for the current pixel position,
        # while the persisted state is authoritative only for the oriented
        # diameter semantics.  A normal sub-pixel centroid drift must not
        # leave ``axis * signed_radius`` pointing at the old pixel: the model
        # intentionally validates that exact invariant when it is seeded.
        # Choose the representation of the fresh undirected line that stays
        # closest to the old oriented axis, then derive its exact coordinate.
        if axis.dot(visible_axis) >= 0.0:
            axis = visible_axis
            signed_radius = visible_radius
        else:
            axis = visible_axis * -1.0
            signed_radius = -visible_radius
        last_side = 1 if signed_radius > 0.0 else -1
        last_axis = visible_axis
    return axis, signed_radius, last_side, last_axis


def calibration_from_detected_handle(handle, wheel_state=None):
    """Convert the formal detector payload into the lab runtime calibration.

    ``wheel_state`` may contain the formal controller's learned effective outer
    limit.  It is reused only when it is geometrically valid for the currently
    detected handle; a stale limit can therefore never place the handle beyond
    the runtime rim.
    """

    if not isinstance(handle, dict):
        return None
    center_x = _finite_float(handle.get("wheel_center_x"))
    center_y = _finite_float(handle.get("wheel_center_y"))
    handle_x = _finite_float(handle.get("x"))
    handle_y = _finite_float(handle.get("y"))
    visual_radius = _finite_float(handle.get("visual_radius"))
    if visual_radius is None:
        visual_radius = _finite_float(handle.get("wheel_radius"))
    if None in (center_x, center_y, handle_x, handle_y, visual_radius):
        return None
    if visual_radius <= 0.0:
        return None

    center = Vec2(center_x, center_y)
    point = Vec2(handle_x, handle_y)
    offset = point - center
    handle_radius = offset.length

    previous_handle = None
    if isinstance(wheel_state, dict):
        candidate = wheel_state.get("last_detected_handle")
        if isinstance(candidate, dict):
            previous_handle = candidate
    persisted_state = None
    # A previous smooth state carries orientation/side that a new screenshot
    # cannot observe at centre or along the horizontal canonicalization seam.
    # It wins only after the fresh point proves the geometry is still the same.
    for source in (previous_handle, handle):
        persisted_state = _persisted_diameter_state(source, center, point)
        if persisted_state is not None:
            break
    if (
        persisted_state is not None
        and handle_radius < WHEEL_DIAMETER_CENTER_FEEDBACK_IGNORE_RADIUS
    ):
        # The detector's centre component has an unstable angle.  Use the
        # matching exact logical coordinate, which may be a real sub-pixel
        # radius, so WheelModel can preserve both position and diameter axis.
        point = center + persisted_state[0] * persisted_state[1]
        offset = point - center
        handle_radius = offset.length

    learned_limit = None
    for source in (handle, wheel_state if isinstance(wheel_state, dict) else None):
        if not source:
            continue
        candidate = _finite_float(source.get("effective_max_radius"))
        if candidate is not None and candidate >= 8.0:
            learned_limit = candidate
    max_radius = visual_radius
    if learned_limit is not None:
        max_radius = min(visual_radius, learned_limit)
    max_radius = max(max_radius, handle_radius)
    if not math.isfinite(max_radius) or max_radius < 8.0 or max_radius > 2000.0:
        return None

    if handle_radius > 1e-6:
        axis = offset.normalized()
    elif persisted_state is not None:
        axis = persisted_state[0]
    else:
        axis_angle = _finite_float(handle.get("radial_axis_angle"))
        if axis_angle is None and isinstance(wheel_state, dict):
            axis_angle = _finite_float(wheel_state.get("radial_axis_angle"))
            if axis_angle is None:
                previous = wheel_state.get("last_detected_handle")
                if isinstance(previous, dict):
                    axis_angle = _finite_float(previous.get("radial_axis_angle"))
        axis = (
            Vec2(math.cos(axis_angle), math.sin(axis_angle))
            if axis_angle is not None
            else Vec2(1.0, 0.0)
        )
    if persisted_state is None:
        persisted_axis = None
        persisted_signed_radius = None
        persisted_last_side = None
        persisted_last_axis = None
    else:
        (
            persisted_axis,
            persisted_signed_radius,
            persisted_last_side,
            persisted_last_axis,
        ) = persisted_state
    calibration = Calibration(
        center=center,
        handle=point,
        rim=center + axis * max_radius,
        source="formal-auto-recognition",
        confidence=_finite_float(handle.get("confidence")),
        diameter_axis=persisted_axis,
        signed_radius=persisted_signed_radius,
        diameter_last_side=persisted_last_side,
        last_nonzero_axis=persisted_last_axis,
        visual_radius=visual_radius,
    )
    return calibration if calibration.valid else None


class FormalWheelController(WheelWorkerController):
    """Wheel-lab controller with formal recognition supplied externally."""

    def __init__(
        self,
        *,
        calibration: Calibration,
        bindings: Optional[MacOSBindings] = None,
        last_mouse_down_at: Optional[float] = None,
        target_valid_callback: Optional[Callable[[], bool]] = None,
        pointer_state_callback: Optional[Callable[[bool], None]] = None,
        emit_event: Optional[Callable[[dict], None]] = None,
        numeric_capture=None,
    ):
        self._formal_pointer_state_callback = pointer_state_callback or (
            lambda _down: None
        )
        self._formal_pointer_state_lock = Lock()
        self._formal_pointer_down = False
        self._formal_target_valid = target_valid_callback or (lambda: True)
        super().__init__(bindings=bindings, emit_event=emit_event)
        # Optional, read-only capture companion. It never supplies control state.
        self._numeric_capture = numeric_capture
        with self._lock:
            self._calibration = calibration
            previous_down = _finite_float(last_mouse_down_at)
            if previous_down is not None and previous_down >= 0.0:
                self._last_mouse_down_at = previous_down

    def _resolve_live_calibration(self, fallback: Calibration) -> Calibration:
        """Use the formal detector result and validate every mutable live gate."""

        if not self._formal_target_valid():
            raise WorkerError(
                "formal_target_changed",
                "the pointer or hovered wheel changed during recognition",
            )
        problems = fallback.errors()
        if problems or fallback.handle is None:
            raise WorkerError("calibration_invalid", ", ".join(problems))

        initial = self.preflight()
        failures = self._live_setup_failures(initial)
        if failures:
            raise WorkerError("live_preflight_failed", "; ".join(failures))
        initial_pid = initial["frontmost"]["pid"]

        if not self._formal_target_valid():
            raise WorkerError(
                "formal_target_changed",
                "the pointer or hovered wheel changed before cursor placement",
            )

        try:
            self._bindings.warp_mouse_cursor(
                (fallback.handle.x, fallback.handle.y)
            )
            mouse_x, mouse_y = self._bindings.current_mouse_position()
        except Exception as exc:
            raise WorkerError(
                "formal_recognition_warp_failed",
                "recognized the wheel but could not place the pointer on its handle: %s"
                % exc,
            ) from exc

        if math.hypot(
            float(mouse_x) - fallback.handle.x,
            float(mouse_y) - fallback.handle.y,
        ) > 3.0:
            raise WorkerError(
                "formal_recognition_warp_failed",
                "recognized the wheel but the pointer did not reach its handle",
            )

        second = self.preflight()
        if not self._formal_target_valid():
            raise WorkerError(
                "formal_target_changed",
                "the hovered wheel changed while the session was arming",
            )
        failures = self._live_setup_failures(second)
        if second["frontmost"]["pid"] != initial_pid:
            failures.append(
                "frontmost DaVinci process changed during formal recognition"
            )
        if failures:
            raise WorkerError("live_preflight_failed", "; ".join(failures))
        with self._lock:
            self._calibration = fallback
        return fallback

    def _arm_live(self, model, engine_config, handle) -> None:
        # At the exact centre the pixels contain no hue direction.  Seed the
        # model from the formal plugin's persisted radial axis (encoded by the
        # calibration rim) before the lab runtime starts its live session.
        with self._lock:
            calibration = self._calibration
        if (
            calibration.diameter_axis is not None
            and calibration.signed_radius is not None
        ):
            model.seed_diameter_state(
                calibration.diameter_axis,
                calibration.signed_radius,
                diameter_last_side=calibration.diameter_last_side,
                last_nonzero_axis=calibration.last_nonzero_axis,
            )
        elif model.radius <= 1e-6:
            if calibration.center is not None and calibration.rim is not None:
                rim_axis = calibration.rim - calibration.center
                if rim_axis.length > 1e-6:
                    model.seed_center_axis(rim_axis)
        result = super()._arm_live(model, engine_config, handle)
        if not self._formal_target_valid():
            try:
                self.cancel("formal_target_changed")
            finally:
                raise WorkerError(
                    "formal_target_changed",
                    "the hovered wheel changed while native input was arming",
                )
        return result

    def _on_pointer_state(self, down: bool) -> None:
        # Runner DOWN and failsafe UP may originate on different threads.
        # Serialize the base controller state, formal mirror and manager
        # callback as one ordered transition; otherwise UP can overtake DOWN
        # between the two layers and leave plugin mouse depth permanently set.
        with self._formal_pointer_state_lock:
            super()._on_pointer_state(down)
            callback = None
            down = bool(down)
            if down != self._formal_pointer_down:
                self._formal_pointer_down = down
                callback = self._formal_pointer_state_callback
            if callback is not None:
                try:
                    callback(down)
                except Exception:
                    # Manager bookkeeping is observational; the native
                    # failsafe remains authoritative for the real mouse
                    # button lifecycle.
                    pass


class FormalWheelSession:
    """Small session facade used by :class:`SmoothWheelBackend`."""

    def __init__(
        self,
        *,
        calibration: Calibration,
        pointer_state_callback: Callable[[bool], None],
        event_callback: Optional[Callable[[dict], None]] = None,
        bindings: Optional[MacOSBindings] = None,
        last_mouse_down_at: Optional[float] = None,
        target_valid_callback: Optional[Callable[[], bool]] = None,
        controller_factory=FormalWheelController,
        clock=time.monotonic,
    ):
        self._calibration = calibration
        self._clock = clock
        self._controller = controller_factory(
            calibration=calibration,
            bindings=bindings or MacOSBindings(),
            last_mouse_down_at=last_mouse_down_at,
            target_valid_callback=target_valid_callback,
            pointer_state_callback=pointer_state_callback,
            emit_event=event_callback,
        )
        try:
            self._controller.configure(
                {
                    "outputMode": "live",
                    "orbitStepDeg": 1.0,
                    "pushPullStepPx": 1.0,
                    "speedProfile": "tourbox_like",
                    "simulator": False,
                }
            )
            self._controller.arm()
            self._cadence_enable_at = self._clock() + _STARTUP_CADENCE_GUARD_SECONDS
        except Exception as exc:
            # Arm has its own bounded native rollback.  Shutdown additionally
            # closes diagnostics and makes a partially constructed facade
            # impossible to leak a worker thread.
            rollback = None
            try:
                rollback = self._controller.shutdown("session_start_failed")
            except Exception:
                rollback = None
            if (
                isinstance(exc, WorkerError)
                and exc.code != "formal_target_changed"
                and _clean_shutdown_result(rollback)
                and not bool(
                    getattr(self._controller, "_formal_pointer_down", False)
                )
            ):
                raise SmoothWheelUnavailable(exc.code, str(exc)) from exc
            raise

    def submit(self, mode, ticks, context, sensitivity=1.0):
        parsed_ticks = _finite_float(ticks)
        parsed_sensitivity = _finite_float(sensitivity)
        if (
            parsed_ticks is None
            or parsed_ticks == 0.0
            or parsed_sensitivity is None
            or parsed_sensitivity <= 0.0
        ):
            return False
        parsed_sensitivity = max(0.1, min(10.0, parsed_sensitivity))
        direction = 1.0 if parsed_ticks > 0.0 else -1.0
        amount = abs(parsed_ticks) * parsed_sensitivity
        self._controller.input(
            {
                "mode": mode,
                "direction": direction,
                "amount": amount,
                "context": context,
                "hostRotateEvent": "right" if direction > 0 else "left",
                "tuningVersion": 4,
                "rawEventsPerDetent": 5,
                "rawEventWeight": 0.2,
                "appliedEventWeight": 1.0,
                "perHostEventAmount": amount,
                # The SDK invokes actions synchronously on its websocket
                # callback. Events which arrived while the first recognition
                # armed can therefore be delivered in a false <35 ms burst.
                "disableCadence": self._clock() < self._cadence_enable_at,
            }
        )
        return True

    def cancel(self, reason="cancel"):
        # A formal session is not reused after cancellation. Shutdown also
        # closes its bounded diagnostic thread after the native failsafe path.
        return self._controller.shutdown(reason)

    def close(self, reason="shutdown"):
        return self._controller.shutdown(reason)

    def process_events(self):
        return []

    def snapshot(self):
        return self._controller.status(include_preflight=False)


class SmoothWheelBackend:
    """Lossless macOS wheel adapter with a tri-state legacy fallback result."""

    def __init__(
        self,
        *,
        platform_name=None,
        recognize_fn,
        session_factory=FormalWheelSession,
        mark_down_fn=None,
        mark_up_fn=None,
        commit_state_fn=None,
        invalidate_visual_fn=None,
        refresh_invalidated_visual_fn=None,
        target_valid_fn=None,
        session_target_valid_fn=None,
        restore_pointer_fn=None,
        debug_slow_fn=None,
        diagnostic_trace=None,
        clock=time.monotonic,
    ):
        self._platform_name = platform_name or platform.system()
        self._recognize_fn = recognize_fn
        self._session_factory = session_factory
        self._mark_down_fn = mark_down_fn or (lambda: None)
        self._mark_up_fn = mark_up_fn or (lambda: None)
        self._commit_state_fn = commit_state_fn
        self._invalidate_visual_fn = invalidate_visual_fn
        self._refresh_invalidated_visual_fn = refresh_invalidated_visual_fn
        self._visual_invalidated_session = None
        self._pending_visual_refresh = None
        self._target_valid_fn = target_valid_fn or (lambda _area: True)
        self._session_target_valid_fn = (
            session_target_valid_fn or self._target_valid_fn
        )
        self._restore_pointer_fn = restore_pointer_fn
        self._debug = debug_slow_fn or (lambda _message: None)
        self._diagnostic_trace = diagnostic_trace
        self._numeric_trace = None
        self._numeric_diagnostic_reported = None
        self._diagnostic_reported = None
        self._clock = clock
        self._lock = RLock()
        # DOWN and UP may arrive from the runner and safety/failsafe threads.
        # Keep the external depth callbacks in the same total order as the
        # internal boolean without holding the general state lock while user
        # code executes.
        self._pointer_callback_lock = Lock()
        # Action callbacks can originate on SDK threads while the manager
        # pumps status on its UI thread.  Only one caller may create, replace,
        # submit to, or close a native session at a time; pointer/status
        # callbacks deliberately use the separate state lock above.
        self._lifecycle_lock = RLock()
        self._session = None
        self._area = None
        self._target_key = None
        self._session_active = False
        self._pointer_down = False
        self._dirty = False
        self._last_committed_revision = None
        self._last_error = None
        self._ended_pending = False
        self._last_mouse_down_at = None
        self._suspensions = set()
        self._closed = False
        self._discard_final_commit = False
        self._unavailable_until = {}
        self._last_recovery_session_id = None
        self._diameter_continuity = DiameterContinuity()
        self._diameter_epoch = 0
        self._diameter_session_epoch = None
        self._diameter_calibration = None
        self._diameter_invalidated_at = 0.0
        self.record_diagnostic("backend_created", runtime=FORMAL_SMOOTH_RUNTIME_VERSION,
                               diagnosticVersion="axis.1-trace.3", centerContinuityVersion="axis.1-center.1",
                               axisRearmVersion="axis.1-center.2",
                               confirmedGeometryVersion="geometry.1",
                               pushPullAccelerationVersion="pushaccel.4",
                               orbitAccelerationVersion="orbitaccel.7",
                               buttonPollVersion="buttonpoll.1",
                               axisAlignmentVersion="axisalign.1",
                               orbitRecoveryVersion="orbitrecover.3",
                               rimHandleVersion="rimhandle.1",
                               transportTraceVersion="transporttrace.1",
                               rebaseFixVersion="rebasefix.1",
                               rebaseCursorVersion="rebasecursor.1",
                               rebaseControlVersion="normal.100",
                               rebaseControlEdgeMargin=100.0,
                               cadenceTraceVersion="cadencetrace.1",
                               orbitContinuityVersion="orbitflow.1",
                               orbitPacingVersion="orbitpace.2",
                               resetVisualVersion="resetvisual.1",
                               windowsCaptureTraceVersion=("windows-capture.1" if self._platform_name == "Windows" else None),
                               windowsCaptureGateVersion=("windows-capture-gate.2" if self._platform_name == "Windows" else None),
                               windowsModelCommitVersion=("windows-model-commit.1" if self._platform_name == "Windows" else None),
                               platform=self._platform_name)

    def record_diagnostic(self, event, **fields):
        """Enqueue only; diagnostics must never change ownership or input flow."""
        trace = self._diagnostic_trace
        if trace is None:
            return False
        try:
            return trace.record({"event": event, "monotonic": time.monotonic(),
                                 "wallTimeMs": time.time() * 1000.0, **fields})
        except Exception:
            return False

    def _record_cadence_sample(self, snapshot, started_at):
        """Observe sampled model progress, including zero-radius/no-pointer orbit."""
        if self._diagnostic_trace is None:
            return
        try:
            stats = snapshot.get("statistics") or {}
            now = time.monotonic()
            key = (snapshot.get("sessionId"), stats.get("motionRevision"),
                   stats.get("modelRevision"))
            if key != getattr(self, "_cadence_sample_key", None):
                self._cadence_sample_key = key
                self._cadence_sample_changed_at = now
            if (snapshot.get("state") not in _ACTIVE_STATES or
                    now - self._cadence_sample_changed_at > 0.3):
                return
            self.record_diagnostic(
                "cadence_model_sample", sessionId=key[0],
                sampleStartedAt=started_at, sampleFinishedAt=now,
                threadName=current_thread().name,
                **{name: stats.get(name) for name in (
                    "motionRevision", "modelRevision", "consumedAngle",
                    "pendingAngle", "consumedRadial", "pendingRadial",
                    "modelRadius", "lastNonzeroAxis", "diameterAxis",
                    "freshHandleBarrier", "sessionActive")})
        except Exception:
            pass

    def _report_diagnostic_status(self):
        if self._numeric_trace is not None:
            try:
                numeric_status = self._numeric_trace.status()
                numeric_key = (bool(numeric_status.get("ready")),
                               bool(numeric_status.get("finished")),
                               numeric_status.get("error"), numeric_status.get("dropped"),
                               numeric_status.get("ocrDropped"),
                               bool((numeric_status.get("budget") or {}).get("exhausted")))
                if numeric_key != self._numeric_diagnostic_reported:
                    self._numeric_diagnostic_reported = numeric_key
                    self._debug("wheel-numeric-trace status=%s" % numeric_status)
            except Exception:
                pass
        trace = self._diagnostic_trace
        if trace is None:
            return
        try:
            status = trace.status()
            report_key = (bool(status.get("ready")), status.get("error"),
                          bool((status.get("budget") or {}).get("exhausted")),
                          bool(status.get("dropped")))
            if report_key != self._diagnostic_reported:
                self._diagnostic_reported = report_key
                self._debug("wheel-axis-trace status=%s" % status)
        except Exception:
            pass

    def _diagnostic_axis_state(self):
        with self._lock:
            state = self._diameter_continuity._state
            if state is None:
                return None
            key, center, radius, axis, side, last_axis = state
            return {"key": key, "center": {"x": center.x, "y": center.y},
                    "visualRadius": radius, "axis": {"x": axis.x, "y": axis.y},
                    "lastSide": side, "lastNonzeroAxis": {"x": last_axis.x, "y": last_axis.y}}

    def invalidate_diameter(self, reason="external_change"):
        """Short, mouse-callback-safe invalidation; never waits for native UP."""
        with self._lock:
            previous = self._diagnostic_axis_state() if self._diagnostic_trace is not None else None
            self._diameter_continuity.invalidate()
            self._diameter_epoch += 1
            self._diameter_invalidated_at = time.time()
        # Repeated inactive hover-cleared polling is already in the host log;
        # preserve only meaningful intent transitions in the detailed trace.
        if previous is not None or reason != "hover_cleared":
            self.record_diagnostic("axis_invalidated", reason=reason, previous=previous,
                                   epoch=self._diameter_epoch)
        self._debug("smooth wheel diameter invalidated reason=%s" % reason)

    @staticmethod
    def _axis_only_retirement_is_safe(snapshot):
        last = snapshot.get("lastSession") or {}
        reason = str(last.get("reason") or snapshot.get("lastCancelReason") or "")
        if reason in _SAFE_AUTONOMOUS_FINAL_REASONS:
            return True
        # Keep direction (NOT the old predicted position or a replay permit)
        # through a proven internal native-event fault. Real external input,
        # lost permissions/focus/display or unknown provenance invalidates it.
        stats = last.get("statistics") or snapshot.get("statistics") or {}
        interlock = stats.get("interlock") or {}
        return bool(
            reason in {"tagged_event_not_confirmed", "external_left_button_down"}
            and last.get("releaseOk") is True
            and interlock.get("externalEvents") == 0
            and "lastExternalEvent" in interlock
            and interlock.get("lastExternalEvent") is None
            and "cancelEvent" in interlock
            and interlock.get("cancelEvent") is None
        )

    def _geometry_output_ready(self, snapshot, statistics=None):
        if self._platform_name != "Windows":
            return True
        stats = statistics if statistics is not None else (snapshot.get("statistics") or {})
        return bool(
            not snapshot.get("windowsIdleRecalibrationRequired", False)
            and not stats.get("transportPending", False)
            and stats.get("modelOutputReady", True)
            and not (snapshot.get("state") in _ACTIVE_STATES
                     and stats.get("engineCancelled", False))
        )

    def _invalidate_idle_prediction(self, session, area, snapshot):
        if (self._platform_name != "Windows" or not area
                or not snapshot.get("windowsIdleRecalibrationRequired")
                or self._visual_invalidated_session is session):
            return
        self._visual_invalidated_session = session
        self.invalidate_diameter(_WINDOWS_IDLE_RECALIBRATION_REASON)
        self._discard_final_commit = True
        self._last_committed_revision = None
        if callable(self._invalidate_visual_fn):
            try:
                # This callback changes data only; SDK admission can run here.
                if self._invalidate_visual_fn(area, _WINDOWS_IDLE_RECALIBRATION_REASON):
                    self._pending_visual_refresh = dict(area)
            except Exception as exc:
                self._debug("smooth wheel visual invalidation failed: %s" % exc)

    def _remember_diameter_snapshot(self, snapshot):
        with self._lock:
            if (self._diameter_session_epoch != self._diameter_epoch
                    or self._diameter_calibration is None or self._area is None):
                return
            active = snapshot.get("state") in _ACTIVE_STATES
            if not active and not self._axis_only_retirement_is_safe(snapshot):
                self.invalidate_diameter(self._snapshot_cancel_reason(snapshot) or "unknown_retirement")
                return
            stats = snapshot.get("statistics") or {}
            if not active:
                stats = (snapshot.get("lastSession") or {}).get("statistics") or stats
            if not self._geometry_output_ready(snapshot, stats):
                return
            if stats.get("modelHandle") and stats.get("diameterAxis"):
                self._diameter_continuity.remember(self._area, self._diameter_calibration, stats)

    @staticmethod
    def _unavailable_key(area):
        """Bind startup backoff to both logical target and current layout."""

        return (
            area_key(area),
            _finite_float(area.get("x")) if isinstance(area, dict) else None,
            _finite_float(area.get("y")) if isinstance(area, dict) else None,
            _finite_float(area.get("w")) if isinstance(area, dict) else None,
            _finite_float(area.get("h")) if isinstance(area, dict) else None,
        )

    def _startup_is_cooling_down(self, area):
        key = self._unavailable_key(area)
        now = self._clock()
        with self._lock:
            entry = self._unavailable_until.get(key)
            if entry is None:
                return False
            _code, deadline = entry
            if now >= deadline:
                self._unavailable_until.pop(key, None)
                return False
            return True

    def _remember_startup_unavailable(self, area, code):
        if code not in _COOLDOWN_UNAVAILABLE_CODES:
            return
        key = self._unavailable_key(area)
        with self._lock:
            self._unavailable_until[key] = (
                code,
                self._clock() + _UNAVAILABLE_RETRY_SECONDS,
            )

    def _clear_startup_cooldown(self, area=None):
        with self._lock:
            if area is None:
                self._unavailable_until.clear()
            else:
                self._unavailable_until.pop(self._unavailable_key(area), None)

    @property
    def active_area(self):
        with self._lock:
            return self._area if self._session_active else None

    def is_active(self):
        with self._lock:
            return bool(self._session is not None and self._session_active)

    def _pointer_state_changed(self, down):
        with self._pointer_callback_lock:
            callback = None
            with self._lock:
                down = bool(down)
                if down == self._pointer_down:
                    return
                self._pointer_down = down
                if down:
                    self._last_mouse_down_at = time.monotonic()
                callback = self._mark_down_fn if down else self._mark_up_fn
            callback()

    def _on_session_event(self, event):
        if self._diagnostic_trace is not None:
            # TraceBuffer batches already have native/source timestamps and
            # session IDs. Retain them rather than formatting on pointer paths.
            self.record_diagnostic("runtime", payload=event)
        with self._lock:
            self._dirty = True
            if not isinstance(event, dict) or event.get("type") != "status":
                return
            state = (event.get("status") or {}).get("state")
            if state:
                active = state in _ACTIVE_STATES
                if self._session is not None and self._session_active and not active:
                    self._ended_pending = True
                self._session_active = active

    @staticmethod
    def _cancel_is_complete(result, session=None):
        if isinstance(result, bool):
            complete = result
        elif not isinstance(result, dict):
            complete = True
        else:
            complete = not bool(result.get("cleanupPending")) and result.get(
                "state", "disarmed"
            ) == "disarmed"
        if not complete or session is None:
            return complete

        # The controller's native DOWN/DRAG resources are already safe when
        # ``complete`` is true.  Its visual observer has a deliberately
        # independent bounded shutdown, though.  Retain the retired session
        # until that thread is gone so a new controller cannot start a second
        # screenshot daemon against the same wheel.
        try:
            observer = (session.snapshot() or {}).get("observer") or {}
        except Exception:
            return False
        return not bool(observer.get("alive"))

    def _cancel_current(self, reason, *, close=False):
        if reason not in {"session_disarmed", "input_failed"}:
            self.invalidate_diameter(reason)
        else:
            with self._lock:
                retiring = self._session
            if retiring is not None:
                try:
                    retirement = retiring.snapshot() or {}
                    self._remember_diameter_snapshot(retirement)
                    self._debug("smooth wheel session retired reason=%s axis=%s" % (
                        self._snapshot_cancel_reason(retirement) or reason,
                        self._diameter_continuity.last_decision,
                    ))
                except Exception:
                    self.invalidate_diameter("retirement_snapshot_failed")
        with self._lock:
            session = self._session
            if session is None:
                self._session_active = False
                self._area = None
                self._target_key = None
                self._ended_pending = False
                return True
            self._session_active = False
            self._ended_pending = False
            self._discard_final_commit = True
        try:
            result = (
                session.close(reason)
                if close
                else session.cancel(reason)
            )
        except Exception as exc:
            result = {"state": "cleanup_pending", "cleanupPending": True}
            with self._lock:
                self._last_error = str(exc)
            self._debug("smooth wheel cancel failed reason=%s error=%s" % (reason, exc))
        complete = self._cancel_is_complete(result, session)
        if complete:
            with self._lock:
                if self._session is session:
                    self._session = None
                    self._area = None
                    self._target_key = None
                    self._dirty = False
                    self._last_committed_revision = None
                    self._ended_pending = False
                    self._discard_final_commit = False
        return complete

    @staticmethod
    def _tagged_confirmation_recovery_evidence(snapshot):
        """Return a fail-closed cursor recovery record for one exact fault."""

        if not isinstance(snapshot, dict) or snapshot.get("state") != "disarmed":
            return None
        last_session = snapshot.get("lastSession")
        if not isinstance(last_session, dict):
            return None
        if str(last_session.get("reason") or "") != "tagged_event_not_confirmed":
            return None
        if last_session.get("releaseOk") is not True:
            return None
        statistics = last_session.get("statistics")
        if not isinstance(statistics, dict):
            return None
        interlock = statistics.get("interlock")
        if not isinstance(interlock, dict):
            return None
        external_events = _finite_float(interlock.get("externalEvents"))
        if external_events is None or external_events != 0.0:
            return None
        if (
            "lastExternalEvent" not in interlock
            or interlock.get("lastExternalEvent") is not None
        ):
            return None
        if "cancelEvent" not in interlock or interlock.get("cancelEvent") is not None:
            return None
        if interlock.get("ownerDown") is not False:
            return None
        failure = interlock.get("confirmationFailure")
        if not isinstance(failure, dict) or failure.get("reason") != (
            "tagged_event_not_confirmed"
        ):
            return None
        failure_pending = _finite_float(failure.get("pendingConfirmations"))
        if failure_pending is None or failure_pending <= 0.0:
            return None
        failure_checked_at = _finite_float(failure.get("checkedAt"))
        expired = failure.get("expired")
        if (
            failure_checked_at is None
            or not isinstance(expired, dict)
            or expired.get("kind") != "drag"
        ):
            return None
        posted = _finite_float(interlock.get("postedEvents"))
        confirmed = _finite_float(
            interlock.get("confirmedPosts"),
            _finite_float(interlock.get("confirmedEvents")),
        )
        pending = _finite_float(interlock.get("pendingConfirmations"), 0.0)
        if (
            posted is None
            or confirmed is None
            or pending is None
        ):
            return None
        last_posted = interlock.get("lastPostedEvent")
        if not isinstance(last_posted, dict) or last_posted.get("kind") != "up":
            return None
        transport_position = last_posted.get("position")
        if not isinstance(transport_position, dict):
            return None
        transport_x = _finite_float(transport_position.get("x"))
        transport_y = _finite_float(transport_position.get("y"))
        if transport_x is None or transport_y is None:
            return None
        handle = statistics.get("modelHandle")
        if not isinstance(handle, dict):
            return None
        point_x = _finite_float(handle.get("x"))
        point_y = _finite_float(handle.get("y"))
        if point_x is None or point_y is None:
            return None
        session_id = last_session.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            return None
        return {
            "sessionId": session_id,
            "point": (point_x, point_y),
            "transportPoint": (transport_x, transport_y),
            "posted": int(posted),
            "confirmed": int(confirmed),
            "pending": int(pending),
            "failurePending": int(failure_pending),
            "failureCheckedAt": failure_checked_at,
            "failure": dict(failure),
        }

    @staticmethod
    def _snapshot_cancel_reason(snapshot):
        if not isinstance(snapshot, dict):
            return ""
        last_session = snapshot.get("lastSession")
        if isinstance(last_session, dict):
            reason = str(last_session.get("reason") or "")
            if reason:
                return reason
        return str(snapshot.get("lastCancelReason") or "")

    def _attempt_tagged_confirmation_recovery(
        self,
        area,
        session,
        snapshot,
    ):
        evidence = self._tagged_confirmation_recovery_evidence(snapshot)
        if evidence is None or not callable(self._restore_pointer_fn):
            return False
        recovery_age = self._clock() - evidence["failureCheckedAt"]
        if (
            not math.isfinite(recovery_age)
            or recovery_age < 0.0
            or recovery_age > _TAGGED_RECOVERY_MAX_AGE_SECONDS
        ):
            self._debug(
                "smooth wheel tagged confirmation recovery expired "
                "target=%s age_ms=%.1f"
                % ((area_key(area) or "unknown"), recovery_age * 1000.0)
            )
            return False
        session_id = evidence.get("sessionId")
        recovery_id = session_id if session_id is not None else id(session)
        with self._lock:
            if recovery_id == self._last_recovery_session_id:
                return False
            # One fault gets one bounded restore attempt.  A changed target,
            # external pointer, failed warp, or repeated safety fault remains
            # fail-closed instead of repeatedly moving the user's cursor.
            self._last_recovery_session_id = recovery_id
        point = evidence["point"]
        transport_point = evidence["transportPoint"]
        restored = False
        try:
            restored = bool(
                self._restore_pointer_fn(area, point, transport_point)
            )
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
        self._debug(
            "smooth wheel tagged confirmation recovery target=%s "
            "posted=%s confirmed=%s pending=%s failure_pending=%s "
            "transport=(%.1f,%.1f) point=(%.1f,%.1f) restore=%s"
            % (
                area_key(area) or "unknown",
                evidence["posted"],
                evidence["confirmed"],
                evidence["pending"],
                evidence["failurePending"],
                transport_point[0],
                transport_point[1],
                point[0],
                point[1],
                restored,
            )
        )
        return restored

    def try_submit(self, area, ticks, mode, context, sensitivity=1.0):
        with self._lifecycle_lock:
            return self._try_submit_serial(
                area,
                ticks,
                mode,
                context,
                sensitivity,
            )

    def _try_submit_serial(
        self,
        area,
        ticks,
        mode,
        context,
        sensitivity=1.0,
        *,
        _retry_not_armed=True,
        _retry_tagged_confirmation=True,
    ):
        if self._platform_name not in {"Darwin", "Windows"}:
            return None
        if not area or area.get("type") != "wheel":
            return None
        with self._lock:
            unavailable = self._closed or bool(self._suspensions)
            unavailable_reason = (
                "closed"
                if self._closed
                else ",".join(sorted(str(item) for item in self._suspensions))
            )
        if unavailable:
            self._debug(
                "smooth wheel input suppressed state=%s" % unavailable_reason
            )
            return False
        runtime_mode = {"orbit": "orbit", "diameter": "push_pull"}.get(mode)
        if runtime_mode is None:
            return False
        if _finite_float(ticks) in (None, 0.0):
            return False
        target_key = area_key(area)
        with self._lock:
            session = self._session
            current_key = self._target_key
            session_active = self._session_active

        # A cancelled facade may be retained while its bounded observer/native
        # cleanup finishes. Never submit to that disarmed object. Poll once so
        # an already-completed retirement can be replaced without dropping the
        # new tick; otherwise fail closed until the next event.
        if session is not None and not session_active:
            self._process_events_serial(defer_visual_refresh=self._platform_name == "Windows")
            with self._lock:
                session = self._session
                current_key = self._target_key
            if session is not None:
                self._debug("smooth wheel retired session cleanup is still pending")
                return False

        if session is not None and current_key != target_key:
            if not self._cancel_current("target_changed"):
                return False
            session = None

        if session is not None:
            if not self._session_target_is_valid(area):
                self._debug("smooth wheel active target is no longer valid")
                self._cancel_current("target_invalid")
                return False
        elif not self._target_is_valid(area):
            self._debug("smooth wheel target changed before recognition")
            return False

        if session is None:
            # A missing permission/event tap can otherwise synchronously run
            # recognition, two preflights and native rollback for every SDK
            # callback. During this short target/layout-scoped backoff the
            # established path remains immediately available.
            if self._startup_is_cooling_down(area):
                return None
            with self._lock:
                recognition_epoch = self._diameter_epoch
            try:
                calibration = self._recognize_fn(area)
            except Exception as exc:
                calibration = None
                with self._lock:
                    self._last_error = str(exc)
                self._debug("smooth wheel recognition failed: %s" % exc)
            if calibration is None or not getattr(calibration, "valid", False):
                self._debug(
                    "smooth wheel recognition unavailable target=%s"
                    % (target_key or "unknown")
                )
                # Recognition is passive and has not taken mouse ownership.
                # If the selection is still current, preserve the established
                # formal controller as a compatibility fallback.
                return None if self._target_is_valid(area) else False
            if not self._target_is_valid(area):
                self._debug("smooth wheel target changed after recognition")
                return False
            with self._lock:
                if recognition_epoch != self._diameter_epoch:
                    return False
                recognized_calibration = calibration
                previous_axis = self._diagnostic_axis_state() if self._diagnostic_trace is not None else None
                calibration = self._diameter_continuity.restore(
                    area, calibration, preserve_center_axis=(mode == "diameter"),
                )
                axis_decision = self._diameter_continuity.last_decision
            if self._diagnostic_trace is not None:
                self.record_diagnostic("axis_restore", target=target_key, mode=mode,
                                       epoch=recognition_epoch, previousAxis=previous_axis,
                                       decision=axis_decision, before=recognized_calibration.as_dict(),
                                       after=calibration.as_dict())
            self._debug("smooth wheel diameter recognition target=%s axis=%s signed=%s" % (
                target_key, axis_decision, calibration.signed_radius,
            ))
            try:
                session = self._session_factory(
                    calibration=calibration,
                    last_mouse_down_at=self._last_mouse_down_at,
                    target_valid_callback=lambda: self._target_is_valid(area),
                    pointer_state_callback=self._pointer_state_changed,
                    event_callback=self._on_session_event,
                )
            except SmoothWheelUnavailable as exc:
                with self._lock:
                    self._last_error = "%s: %s" % (exc.code, exc)
                self._remember_startup_unavailable(area, exc.code)
                self._debug(
                    "smooth wheel unavailable target=%s code=%s error=%s; "
                    "using legacy wheel path"
                    % (target_key or "unknown", exc.code, exc)
                )
                return None if self._target_is_valid(area) else False
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                self._debug(
                    "smooth wheel arm failed target=%s error=%s"
                    % (target_key or "unknown", exc)
                )
                return False
            self._clear_startup_cooldown(area)
            with self._lock:
                self._session = session
                self._area = dict(area)
                self._target_key = target_key
                self._session_active = True
                self._dirty = True
                self._last_committed_revision = None
                self._last_error = None
                self._ended_pending = False
                self._discard_final_commit = False
                self._diameter_calibration = calibration
                self._diameter_session_epoch = recognition_epoch
                if recognition_epoch == self._diameter_epoch:
                    self._diameter_continuity.remember(area, calibration)
                    self._diameter_invalidated_at = 0.0
            if recognition_epoch != self._diameter_epoch:
                self._cancel_current("context_changed_during_arm")
                return False
            self._debug(
                "smooth wheel armed target=%s center=(%.1f,%.1f) "
                "handle=(%.1f,%.1f) max=%.1f source=%s"
                % (
                    target_key or "unknown",
                    calibration.center.x,
                    calibration.center.y,
                    calibration.handle.x,
                    calibration.handle.y,
                    calibration.max_radius,
                    calibration.source,
                )
            )
            if self._diagnostic_trace is not None:
                self.record_diagnostic("formal_arm", target=target_key, area=dict(area),
                                       calibration=calibration.as_dict(), epoch=recognition_epoch)

        try:
            accepted = bool(
                session.submit(
                    runtime_mode,
                    ticks,
                    context,
                    sensitivity,
                )
            )
        except WorkerError as exc:
            try:
                failure_snapshot = session.snapshot() or {}
            except Exception:
                failure_snapshot = {}
            with self._lock:
                self._last_error = str(exc)
            if exc.code == "not_armed" and _retry_not_armed:
                cancel_reason = self._snapshot_cancel_reason(failure_snapshot)
                if (
                    self._platform_name == "Windows"
                    and failure_snapshot.get("windowsIdleRecalibrationRequired")
                    and failure_snapshot.get("lastCancelReason") == _WINDOWS_IDLE_RECALIBRATION_REASON
                ):
                    # This tick was rejected before admission by an idle
                    # visual correction retiring the old generation. Invalidate
                    # its cached position/axis and require fresh recognition;
                    # replay only this tick, once, after complete cleanup.
                    self._invalidate_idle_prediction(session, area, failure_snapshot)
                    if self._cancel_current(_WINDOWS_IDLE_RECALIBRATION_REASON, close=True):
                        return self._try_submit_serial(
                            area, ticks, mode, context, sensitivity,
                            _retry_not_armed=False,
                            _retry_tagged_confirmation=False,
                        )
                    return False
                tagged_recovery = self._tagged_confirmation_recovery_evidence(
                    failure_snapshot
                )
                if tagged_recovery is not None:
                    self._debug(
                        "smooth wheel stale session carries tagged confirmation "
                        "failure target=%s; restoring before one replay"
                        % (target_key or "unknown")
                    )
                    cleanup_complete = self._cancel_current(
                        "session_disarmed",
                        close=True,
                    )
                    restored = bool(
                        _retry_tagged_confirmation
                        and self._attempt_tagged_confirmation_recovery(
                            area,
                            session,
                            failure_snapshot,
                        )
                    )
                    if (
                        restored
                        and cleanup_complete
                        and _retry_tagged_confirmation
                    ):
                        return self._try_submit_serial(
                            area,
                            ticks,
                            mode,
                            context,
                            sensitivity,
                            _retry_not_armed=False,
                            _retry_tagged_confirmation=False,
                        )
                    return False
                if cancel_reason not in (
                    "",
                    "startup_disarmed",
                    "idle",
                    "normal_completion",
                    "visual_confirmed",
                ):
                    self._debug(
                        "smooth wheel stale session has unsafe cancellation "
                        "provenance target=%s reason=%s; tick was not replayed"
                        % (target_key or "unknown", cancel_reason)
                    )
                    self._cancel_current("session_disarmed", close=True)
                    return False
                self._debug(
                    "smooth wheel stale session target=%s mode=%s ticks=%s; "
                    "retiring and replaying once"
                    % (target_key or "unknown", runtime_mode, ticks)
                )
                if self._cancel_current("session_disarmed", close=True):
                    return self._try_submit_serial(
                        area,
                        ticks,
                        mode,
                        context,
                        sensitivity,
                        _retry_not_armed=False,
                        _retry_tagged_confirmation=_retry_tagged_confirmation,
                    )
                self._debug(
                    "smooth wheel stale session cleanup is still pending; "
                    "tick was not replayed"
                )
                return False
            self._debug(
                "smooth wheel input failed target=%s mode=%s ticks=%s error=%s"
                % (target_key or "unknown", runtime_mode, ticks, exc)
            )
            cleanup_complete = self._cancel_current("input_failed")
            restored = bool(
                _retry_tagged_confirmation
                and self._attempt_tagged_confirmation_recovery(
                    area,
                    session,
                    failure_snapshot,
                )
            )
            if (
                restored
                and cleanup_complete
                and _retry_tagged_confirmation
                and exc.code == "safety_cancelled"
                and str(exc) == "tagged_event_not_confirmed"
            ):
                self._debug(
                    "smooth wheel tagged confirmation recovery replaying "
                    "current tick once target=%s" % (target_key or "unknown")
                )
                return self._try_submit_serial(
                    area,
                    ticks,
                    mode,
                    context,
                    sensitivity,
                    _retry_not_armed=False,
                    _retry_tagged_confirmation=False,
                )
            return False
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            self._debug(
                "smooth wheel input failed target=%s mode=%s ticks=%s error=%s"
                % (target_key or "unknown", runtime_mode, ticks, exc)
            )
            self._cancel_current("input_failed")
            return False
        if accepted:
            with self._lock:
                self._dirty = True
        return accepted

    def _target_is_valid(self, area):
        try:
            return bool(self._target_valid_fn(area))
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            self._debug("smooth wheel target validation failed: %s" % exc)
            return False

    def _session_target_is_valid(self, area):
        try:
            return bool(self._session_target_valid_fn(area))
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            self._debug("smooth wheel active target validation failed: %s" % exc)
            return False

    def cancel(self, reason="cancel"):
        reason = str(reason or "cancel")
        with self._lifecycle_lock:
            if reason == "layout_changed":
                self._clear_startup_cooldown()
            return self._cancel_current(reason)

    def suspend(self, reason="suspended", *, token=None):
        """Cancel and latch admission until the matching key is resumed.

        A reason without a token is an idempotent long-lived state latch, not a
        reference count. Concurrent or nested temporary transactions must pass
        their own unique token so one completion cannot resume another.
        """

        reason = str(reason or "suspended")
        suspension_key = reason if token is None else token
        with self._lifecycle_lock:
            if reason == "layout_changed":
                self._clear_startup_cooldown()
            with self._lock:
                self._suspensions.add(suspension_key)
            return self._cancel_current(reason)

    def resume(self, reason="suspended", *, token=None):
        reason = str(reason or "suspended")
        suspension_key = reason if token is None else token
        with self._lifecycle_lock:
            with self._lock:
                self._suspensions.discard(suspension_key)
                return not self._closed

    def run_legacy_if_idle(self, callback):
        """Serialize an established legacy gesture against smooth ownership.

        A legacy queue item may have been popped before a newer encoder event
        starts the smooth session.  Holding the same lifecycle gate around the
        final legacy dispatch makes the ownership decision atomic: either the
        old operation finishes first, or it observes the smooth/transactional
        owner and is discarded.
        """

        with self._lifecycle_lock:
            with self._lock:
                blocked = bool(
                    self._closed
                    or self._suspensions
                    or self._session_active
                    or self._pointer_down
                )
                retired_session = (
                    self._session
                    if self._session is not None and not self._session_active
                    else None
                )
            if not blocked and retired_session is not None:
                try:
                    retired_snapshot = retired_session.snapshot() or {}
                    blocked = bool(
                        retired_snapshot.get("state") == "cleanup_pending"
                        or retired_snapshot.get("pointerDown")
                    )
                except Exception:
                    blocked = True
            if blocked:
                return False
            return callback()

    def run_smooth_transaction(self, callback):
        """Make manager target/legacy-state checks atomic with smooth submit."""

        with self._lifecycle_lock:
            return callback()

    def close(self, reason="shutdown"):
        with self._lifecycle_lock:
            with self._lock:
                self._closed = True
            result = self._cancel_current(str(reason or "shutdown"), close=True)
        if self._numeric_trace is not None:
            try:
                self._numeric_trace.close(timeout=0.25)
            except Exception:
                pass
        if self._diagnostic_trace is not None:
            try:
                self._diagnostic_trace.close(timeout=0.25)
            except Exception:
                pass
        return result

    def process_events(self):
        self._report_diagnostic_status()
        with self._lifecycle_lock:
            result = self._process_events_serial()
            # Only this public manager/UI pump refreshes overlays. Internal
            # admission calls to _process_events_serial must remain data-only.
            area = self._pending_visual_refresh
            self._pending_visual_refresh = None
            if area is not None and callable(self._refresh_invalidated_visual_fn):
                try:
                    self._refresh_invalidated_visual_fn(area)
                except Exception as exc:
                    self._debug("smooth wheel invalidated visual refresh failed: %s" % exc)
            return result

    def _process_events_serial(self, *, defer_visual_refresh=False):
        with self._lock:
            session = self._session
            area = self._area
            discard_final_commit = self._discard_final_commit
        if session is None:
            return {"active": False, "ended": False}

        sample_started_at = time.monotonic()
        try:
            session.process_events()
            snapshot = session.snapshot()
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                ended = self._ended_pending
                self._ended_pending = False
            self._debug("smooth wheel status failed: %s" % exc)
            return {"active": self.is_active(), "ended": ended}

        self._invalidate_idle_prediction(session, area, snapshot)
        self._record_cadence_sample(snapshot, sample_started_at)
        state = snapshot.get("state") if isinstance(snapshot, dict) else None
        if isinstance(snapshot, dict) and state in _ACTIVE_STATES:
            self._remember_diameter_snapshot(snapshot)
        active = state in _ACTIVE_STATES if state is not None else self.is_active()
        ended = False
        with self._lock:
            if self._session is not session:
                return {"active": self._session_active, "ended": False}
            was_active = self._session_active
            self._session_active = bool(active)
            if was_active and not active:
                self._ended_pending = True
            ended = self._ended_pending
            self._ended_pending = False

        commit_snapshot = snapshot
        statistics = snapshot.get("statistics") or {}
        last_session = snapshot.get("lastSession") or {}
        final_reason = str(
            last_session.get("reason")
            or snapshot.get("lastCancelReason")
            or ""
        )
        target_valid_for_commit = (
            bool(area) and self._session_target_is_valid(area)
            and self._diameter_session_epoch == self._diameter_epoch
        )
        allow_final_commit = bool(
            not active
            and not discard_final_commit
            and target_valid_for_commit
            and final_reason in _SAFE_AUTONOMOUS_FINAL_REASONS
        )
        if allow_final_commit:
            final_statistics = last_session.get("statistics") or {}
            if final_statistics.get("modelHandle"):
                statistics = final_statistics
                commit_snapshot = dict(snapshot)
                commit_snapshot["statistics"] = statistics
        if (
            self._commit_state_fn is not None
            and statistics.get("modelHandle")
            and target_valid_for_commit
            and (active or allow_final_commit)
            # Clearing a failed sink's pending queue does not make its planned
            # frame output. The engine receipt survives cleanup/runner exit;
            # keep all prior geometry and the last committed revision on skip.
            and self._geometry_output_ready(snapshot, statistics)
        ):
            model_handle = statistics.get("modelHandle") or {}
            # motionRevision advances when input is admitted, not for every
            # 120 Hz output frame.  Include consumed totals and model geometry
            # so a large lossless batch updates the formal cache all the way
            # to its actual endpoint instead of freezing after the first slice.
            revision = (
                statistics.get("motionRevision"),
                statistics.get("modelRevision"),
                statistics.get("consumedAngle"),
                statistics.get("consumedRadial"),
                model_handle.get("x"),
                model_handle.get("y"),
                statistics.get("effectiveMaxRadius"),
            )
            with self._lock:
                should_commit = (
                    self._session is session
                    and revision != self._last_committed_revision
                )
            if should_commit:
                try:
                    if defer_visual_refresh:
                        commit_snapshot = dict(commit_snapshot, deferVisualRefresh=True)
                    self._commit_state_fn(area, commit_snapshot)
                    with self._lock:
                        if self._session is session:
                            self._last_committed_revision = revision
                            self._dirty = False
                except Exception as exc:
                    self._debug("smooth wheel state commit failed: %s" % exc)

        if state == "disarmed":
            recovery_snapshot = snapshot
            recovery_session = session
            recovery_area = area
            self._cancel_current("session_disarmed", close=True)
            if recovery_area:
                self._attempt_tagged_confirmation_recovery(
                    recovery_area,
                    recovery_session,
                    recovery_snapshot,
                )
        return {"active": bool(active), "ended": ended, "snapshot": snapshot}

    def snapshot(self):
        with self._lock:
            session = self._session
            result = {
                "available": self._platform_name in {"Darwin", "Windows"},
                "active": self._session_active,
                "targetKey": self._target_key,
                "area": dict(self._area) if self._area else None,
                "pointerDown": self._pointer_down,
                "lastError": self._last_error,
                "runtimeVersion": FORMAL_SMOOTH_RUNTIME_VERSION,
                "closed": self._closed,
                "suspended": bool(self._suspensions),
                "suspensions": sorted(str(item) for item in self._suspensions),
            }
        if session is not None:
            try:
                result["session"] = session.snapshot()
            except Exception as exc:
                result["sessionError"] = str(exc)
        return result


def create_manager_smooth_wheel_backend(
    manager,
    *,
    platform_name=None,
    plugin_mouse_button_state,
    bindings=None,
    debug_slow_fn=None,
    diagnostics_enabled=False,
):
    """Compose the smooth backend against the formal manager state boundary."""

    from ..config import WHEEL_HANDLE_CACHE_SECONDS
    from ..wheel_state_accessors import wheel_state_for_area
    from ..wheel_state_detection_commits import (
        store_hover_wheel_handle_from_detection,
    )
    from ..wheel_state_store_bridge import commit_wheel_capability_to_store
    from ..wheel_visual_invalidation import (
        invalidate_predicted_wheel_visual, refresh_invalidated_wheel_visual,
    )

    debug = debug_slow_fn or (lambda _message: None)
    active_platform = platform_name or platform.system()
    active_bindings = bindings
    if active_platform == "Darwin" and active_bindings is None:
        active_bindings = MacOSBindings()
    elif active_platform == "Windows" and active_bindings is None:
        active_bindings = WindowsBindings()
    recognition_metadata = {}
    recognition_metadata_lock = Lock()
    diagnostic_trace = None
    numeric_trace = None
    # Windows needs coordinate/axis evidence without enabling screenshot/OCR
    # diagnostics or verbose synchronous console output on motion callbacks.
    windows_trace = active_platform == "Windows" and os.environ.get(
        "DAVINCI_WINDOWS_MOTION_TRACE", "1"
    ).lower() not in {"0", "false", "no", "off"}
    if windows_trace or (diagnostics_enabled and active_platform == "Darwin"):
        try:
            import atexit
            from .host_trace import HostWheelTrace
            diagnostic_trace = HostWheelTrace()
            atexit.register(diagnostic_trace.close)
            debug("wheel-axis-trace configured path=%s" % diagnostic_trace.status().get("path"))
        except Exception as exc:
            debug("wheel-axis-trace initialization failed: %s" % exc)
        if diagnostic_trace is not None and active_platform == "Darwin":
            try:
                from .numeric_trace import NumericWheelTrace
                numeric_trace = NumericWheelTrace(
                    diagnostic_trace.record, ocr_enabled=False, archive_wheel=True,
                )
                atexit.register(numeric_trace.close)
                debug("wheel-numeric-trace configured same_frame=true channels=Y,R,G,B mode=archive_only wheel_archive=true")
            except Exception as exc:
                debug("wheel-numeric-trace initialization failed: %s" % exc)

    def target_layout_is_valid(area):
        if (
            not area
            or area.get("type") != "wheel"
            or not getattr(manager, "_davinci_running", False)
            or not getattr(manager, "_davinci_active", False)
        ):
            return False

        expected_key = area_key(area)
        expected_bounds = tuple(
            _finite_float(area.get(name)) for name in ("x", "y", "w", "h")
        )
        if None in expected_bounds:
            return False
        matching_area = None
        for candidate in getattr(manager, "areas", ()):
            if area_key(candidate) != expected_key:
                continue
            candidate_bounds = tuple(
                _finite_float(candidate.get(name))
                for name in ("x", "y", "w", "h")
            )
            if None not in candidate_bounds and all(
                abs(left - right) <= 0.5
                for left, right in zip(candidate_bounds, expected_bounds)
            ):
                matching_area = candidate
                break
        if matching_area is None:
            return False

        current = getattr(manager, "current_hover_area", None)
        if current is not None and area_key(current) != expected_key:
            return False
        return True

    def target_is_valid(area):
        if not target_layout_is_valid(area):
            return False
        if active_bindings is None:
            return False
        mouse_x, mouse_y = active_bindings.current_mouse_position()
        expected_bounds = tuple(
            _finite_float(area.get(name)) for name in ("x", "y", "w", "h")
        )
        left, top, width, height = expected_bounds
        return bool(
            left <= float(mouse_x) <= left + width
            and top <= float(mouse_y) <= top + height
        )

    def restore_pointer_after_tagged_failure(area, point, expected_cursor):
        """Restore one internally displaced cursor without relaxing target gates."""

        if not target_layout_is_valid(area) or active_bindings is None:
            return False
        point_x = _finite_float(point[0])
        point_y = _finite_float(point[1])
        expected_cursor_x = _finite_float(expected_cursor[0])
        expected_cursor_y = _finite_float(expected_cursor[1])
        expected_bounds = tuple(
            _finite_float(area.get(name)) for name in ("x", "y", "w", "h")
        )
        if (
            point_x is None
            or point_y is None
            or expected_cursor_x is None
            or expected_cursor_y is None
            or None in expected_bounds
        ):
            return False
        left, top, width, height = expected_bounds
        if not (
            left <= point_x <= left + width
            and top <= point_y <= top + height
        ):
            return False
        try:
            if active_bindings.left_button_down():
                return False
            app = active_bindings.frontmost_app()
            if not app.is_davinci:
                return False
            display_resolver = getattr(
                active_bindings, "display_bounds_for_point", None
            )
            if not callable(display_resolver):
                return False
            before_display = tuple(display_resolver((point_x, point_y)))
            current_x, current_y = active_bindings.current_mouse_position()
            if math.hypot(
                float(current_x) - expected_cursor_x,
                float(current_y) - expected_cursor_y,
            ) > 3.0:
                return False
            if active_bindings.left_button_down() or not target_layout_is_valid(area):
                return False
            app = active_bindings.frontmost_app()
            if not app.is_davinci:
                return False
            current_x, current_y = active_bindings.current_mouse_position()
            if math.hypot(
                float(current_x) - expected_cursor_x,
                float(current_y) - expected_cursor_y,
            ) > 3.0:
                return False
            active_bindings.warp_mouse_cursor((point_x, point_y))
            mouse_x, mouse_y = active_bindings.current_mouse_position()
            after_display = tuple(
                display_resolver((float(mouse_x), float(mouse_y)))
            )
        except Exception:
            return False
        if before_display != after_display:
            return False
        if math.hypot(float(mouse_x) - point_x, float(mouse_y) - point_y) > 3.0:
            return False
        return target_layout_is_valid(area)

    def recognize(area):
        name = area.get("name")
        cached = manager.handles.get(name) if name else None
        cached_source = str((cached or {}).get("source") or "")
        with backend._lock:
            invalidated_at = backend._diameter_invalidated_at
            has_axis = backend._diameter_continuity._state is not None
        if diagnostic_trace is not None:
            backend.record_diagnostic("recognition_begin", target=area_key(area), area=dict(area),
                                      cached=dict(cached) if isinstance(cached, dict) else None,
                                      cachedSource=cached_source, invalidatedAt=invalidated_at,
                                      persistentAxis=backend._diagnostic_axis_state())
        # A failed manual release must not resurrect stale hover/store state.
        # A successful explicit reset/manual observation after invalidation is
        # a new authority and may intentionally choose a different diameter.
        explicit_new_axis = bool(
            cached_source in {"center_reset", "manual_release", "manual_release_center"}
            and _finite_float((cached or {}).get("updated_at"), 0.0) >= invalidated_at
        )
        if explicit_new_axis and not has_axis:
            # An explicit reset/manual commit is semantic input, not a visual
            # cache lease. Its direction remains valid after the 0.8s pixel
            # cache expires; import it before inspecting noisy fresh pixels.
            explicit_calibration = calibration_from_detected_handle(cached)
            with backend._lock:
                if (explicit_calibration is not None
                        and backend._diameter_invalidated_at == invalidated_at):
                    has_axis = backend._diameter_continuity.remember(area, explicit_calibration)
        fresh_axis_required = bool(invalidated_at and not explicit_new_axis)
        cached_fresh = bool(
            cached
            and not fresh_axis_required
            and not cached_source.startswith("smooth_live_prediction")
            and time.time() - float(cached.get("updated_at", 0.0))
            <= WHEEL_HANDLE_CACHE_SECONDS
            and cached.get("wheel_center_x") is not None
            and cached.get("wheel_center_y") is not None
            and cached.get("wheel_radius") is not None
        )
        handle = dict(cached) if cached_fresh else None
        if handle is None:
            expected_handle = (
                dict(cached) if isinstance(cached, dict) and not fresh_axis_required else None
            )
            expected_axis = None
            if expected_handle is not None:
                cached_x = _finite_float(expected_handle.get("x"))
                cached_y = _finite_float(expected_handle.get("y"))
                cached_center_x = _finite_float(
                    expected_handle.get("wheel_center_x")
                )
                cached_center_y = _finite_float(
                    expected_handle.get("wheel_center_y")
                )
                if None not in (
                    cached_x,
                    cached_y,
                    cached_center_x,
                    cached_center_y,
                ) and math.hypot(
                    cached_x - cached_center_x,
                    cached_y - cached_center_y,
                ) <= 6.0:
                    expected_handle["allow_center_candidate"] = True

                axis_angle = _finite_float(
                    expected_handle.get("radial_axis_angle")
                )
                wheel_radius = _finite_float(expected_handle.get("wheel_radius"))
                if axis_angle is not None:
                    expected_axis = {
                        "axis_angle": axis_angle,
                        "axis_tolerance": max(
                            8.0,
                            min(18.0, (wheel_radius or 36.0) * 0.22),
                        ),
                    }
            handle = manager._detect_handle_raw_for_area(
                area,
                expected_handle=expected_handle,
                expected_axis=expected_axis,
            )
        if not handle:
            backend.record_diagnostic("recognition_unavailable", target=area_key(area))
            return None

        if diagnostic_trace is not None:
            backend.record_diagnostic("recognition_raw", target=area_key(area), handle=dict(handle),
                                      source="hover-cache" if cached_fresh else "fresh-capture",
                                      cachedSource=cached_source, explicitNewAxis=explicit_new_axis,
                                      freshAxisRequired=fresh_axis_required)

        state = wheel_state_for_area(
            manager,
            area,
            center_x=handle.get("wheel_center_x"),
            center_y=handle.get("wheel_center_y"),
            wheel_radius=handle.get("wheel_radius"),
        )
        if isinstance(state, dict) and state.get("wheel_radius_mismatch"):
            with backend._lock:
                backend._diameter_continuity.invalidate()
            state = None
            has_axis = False
            fresh_axis_required = True
        if has_axis or fresh_axis_required:
            # The independent record owns orientation. Feed it real fresh x/y,
            # not a short-lived position cache's reconstructed diameter.
            handle = dict(handle)
            for key in ("radial_axis_angle", "signed_radius", "diameter_last_side",
                        "last_nonzero_axis_x", "last_nonzero_axis_y"):
                handle.pop(key, None)
            if isinstance(state, dict):
                state = dict(state)
                state.pop("last_detected_handle", None)
                state.pop("radial_axis_angle", None)
        calibration = calibration_from_detected_handle(handle, state)
        if diagnostic_trace is not None:
            backend.record_diagnostic("recognition_calibration", target=area_key(area),
                                      calibration=calibration.as_dict() if calibration else None,
                                      wheelState=dict(state) if isinstance(state, dict) else None)
        if calibration is not None:
            with recognition_metadata_lock:
                recognition_metadata[area_key(area)] = dict(handle)
            debug(
                "smooth wheel formal recognition "
                "target=%s source=%s center=(%.1f,%.1f) handle=(%.1f,%.1f) "
                "visual=%.1f max=%.1f"
                % (
                    area.get("name") or area_key(area) or "unknown",
                    "hover-cache" if cached_fresh else "fresh-capture",
                    calibration.center.x,
                    calibration.center.y,
                    calibration.handle.x,
                    calibration.handle.y,
                    _finite_float(handle.get("wheel_radius"), 0.0),
                    calibration.max_radius,
                )
            )
        return calibration

    def commit_state(area, snapshot):
        if not isinstance(snapshot, dict) or not area:
            return False
        statistics = snapshot.get("statistics") or {}
        model_handle = statistics.get("modelHandle") or {}
        handle_x = _finite_float(model_handle.get("x"))
        handle_y = _finite_float(model_handle.get("y"))
        calibration = snapshot.get("calibration") or {}
        center = calibration.get("center") or {}
        center_x = _finite_float(center.get("x"))
        center_y = _finite_float(center.get("y"))
        if None in (handle_x, handle_y, center_x, center_y):
            return False

        with recognition_metadata_lock:
            metadata = dict(recognition_metadata.get(area_key(area)) or {})
        # Recognition metadata contains geometry which is still valid for the
        # wheel, plus dynamic handle state from the previous position.  Never
        # combine the old polar state with the new predicted x/y pair.
        for stale_key in (
            "visual_invalidated",
            "x",
            "y",
            "angle",
            "radial_axis_angle",
            "signed_radius",
            "diameter_last_side",
            "last_nonzero_axis_x",
            "last_nonzero_axis_y",
            "radius",
            "control_angle",
            "outer_control_x",
            "outer_control_y",
            "source",
            "updated_at",
        ):
            metadata.pop(stale_key, None)
        wheel_radius = _finite_float(
            metadata.get("wheel_radius"),
            _finite_float(calibration.get("maxRadius")),
        )
        visual_radius = _finite_float(
            metadata.get("visual_radius"),
            wheel_radius,
        )
        if wheel_radius is None or visual_radius is None:
            return False
        effective_max_radius = _finite_float(
            statistics.get("effectiveMaxRadius"),
            wheel_radius,
        )
        feedback = snapshot.get("wheelFeedback") or {}
        observer = snapshot.get("observer") or {}
        last_observation = observer.get("lastResult") or {}
        actual = last_observation.get("actual") or {}
        actual_x = _finite_float(actual.get("x"))
        actual_y = _finite_float(actual.get("y"))
        observed_motion_revision = last_observation.get("motionRevision")
        current_motion_revision = statistics.get("motionRevision")
        pending_motion = abs(
            _finite_float(statistics.get("pendingAngle"), 0.0)
        ) + abs(_finite_float(statistics.get("pendingRadial"), 0.0))
        visually_confirmed = bool(
            feedback.get("lastReason") == "confirmed_model_checkpoint"
            and not feedback.get("needsFreshHandle", True)
            and not statistics.get("sessionActive")
            and pending_motion <= 1e-9
            and last_observation.get("result") == "ready"
            and observed_motion_revision == current_motion_revision
            and actual_x is not None
            and actual_y is not None
            and math.hypot(actual_x - handle_x, actual_y - handle_y) <= 1.5
        )
        source = (
            "smooth_visual_confirmed"
            if visually_confirmed
            else "smooth_live_prediction"
        )
        axis = (
            statistics.get("diameterAxis")
            or statistics.get("lastNonzeroAxis")
            or {}
        )
        axis_x = _finite_float(axis.get("x"))
        axis_y = _finite_float(axis.get("y"))
        center_axis_angle = None
        if (
            axis_x is not None
            and axis_y is not None
            and math.hypot(axis_x, axis_y) > 1e-6
        ):
            center_axis_angle = math.atan2(axis_y, axis_x)
        exact_signed_radius = _finite_float(statistics.get("signedRadius"))
        exact_last_side = statistics.get("diameterLastSide")
        last_axis = statistics.get("lastNonzeroAxis") or {}
        last_axis_x = _finite_float(last_axis.get("x"))
        last_axis_y = _finite_float(last_axis.get("y"))
        payload = {
            **metadata,
            "x": handle_x,
            "y": handle_y,
            "wheel_center_x": center_x,
            "wheel_center_y": center_y,
            "wheel_radius": wheel_radius,
            "visual_radius": visual_radius,
            "visual_center_x": _finite_float(
                metadata.get("visual_center_x"), center_x
            ),
            "visual_center_y": _finite_float(
                metadata.get("visual_center_y"), center_y
            ),
            "effective_max_radius": effective_max_radius,
            "source": source,
            "diameter_last_side": exact_last_side,
            "last_nonzero_axis_x": last_axis_x,
            "last_nonzero_axis_y": last_axis_y,
        }
        stored = store_hover_wheel_handle_from_detection(
            manager,
            area,
            payload,
            source=source,
            center_axis_angle=center_axis_angle,
            exact_axis_angle=center_axis_angle,
            exact_signed_radius=exact_signed_radius,
        )
        state = wheel_state_for_area(
            manager,
            area,
            center_x=center_x,
            center_y=center_y,
            wheel_radius=wheel_radius,
        ) or {}
        stored_payload = dict(
            manager.handles.get(area.get("name")) or payload
        )
        commit_wheel_capability_to_store(
            manager,
            area,
            center_x=center_x,
            center_y=center_y,
            visual_center_x=payload.get("visual_center_x"),
            visual_center_y=payload.get("visual_center_y"),
            wheel_radius=wheel_radius,
            visual_radius=visual_radius,
            effective_max_radius=effective_max_radius,
            outer_control_radius=state.get("outer_control_radius"),
            last_detected_handle=stored_payload,
            source=source,
        )
        if snapshot.get("deferVisualRefresh"):
            # SDK admission may retire a normally completed session. Preserve
            # its final cache point; only the UI refresh waits for public pump.
            backend._pending_visual_refresh = dict(area)
            return bool(stored)
        # Attach the exact sampled revision to the next Qt paint. This only
        # enqueues diagnostics; it must not request another repaint or input.
        try:
            overlay = manager.overlays.get(area_key(area))
            if overlay is not None:
                overlay._smooth_cadence_trace = backend.record_diagnostic
                overlay._smooth_cadence_state = {
                    "sessionId": snapshot.get("sessionId"),
                    "modelRevision": statistics.get("modelRevision"),
                    "consumedAngle": statistics.get("consumedAngle"),
                    "committedAt": time.monotonic(),
                    "commitThreadName": current_thread().name,
                }
        except Exception:
            pass
        refresh = getattr(manager, "_refresh_wheel_overlay_state_fn", None)
        if callable(refresh):
            refresh(area, area.get("name"))
        return bool(stored)

    session_factory = (
        partial(FormalWheelSession, bindings=active_bindings)
        if active_bindings is not None else FormalWheelSession
    )
    if active_platform == "Darwin":
        def diagnostic_controller_factory(**kwargs):
            companion = None
            if numeric_trace is not None:
                try:
                    calibration = kwargs["calibration"]
                    radius = calibration.visual_radius
                    if radius is None:
                        radius = (calibration.rim - calibration.center).length
                    companion = numeric_trace.scope(
                        (calibration.center.x, calibration.center.y),
                        radius,
                        getattr(manager, "areas", ()),
                    )
                except Exception as exc:
                    # Diagnostics may be absent; native arming remains unchanged.
                    debug("wheel-numeric-trace geometry unavailable: %s" % exc)
            return FormalWheelController(numeric_capture=companion, **kwargs)

        session_options = {"bindings": active_bindings}
        if numeric_trace is not None:
            session_options["controller_factory"] = diagnostic_controller_factory
        session_factory = partial(FormalWheelSession, **session_options)
    backend = SmoothWheelBackend(
        platform_name=active_platform,
        recognize_fn=recognize,
        session_factory=session_factory,
        mark_down_fn=plugin_mouse_button_state.mark_down,
        mark_up_fn=plugin_mouse_button_state.mark_up,
        commit_state_fn=commit_state,
        invalidate_visual_fn=partial(invalidate_predicted_wheel_visual, manager),
        refresh_invalidated_visual_fn=partial(refresh_invalidated_wheel_visual, manager),
        target_valid_fn=target_is_valid,
        session_target_valid_fn=target_layout_is_valid,
        restore_pointer_fn=restore_pointer_after_tagged_failure,
        debug_slow_fn=debug,
        diagnostic_trace=diagnostic_trace,
    )
    backend._numeric_trace = numeric_trace
    return backend


__all__ = [
    "FORMAL_SMOOTH_RUNTIME_VERSION",
    "FormalWheelController",
    "FormalWheelSession",
    "SmoothWheelBackend",
    "SmoothWheelUnavailable",
    "calibration_from_detected_handle",
    "create_manager_smooth_wheel_backend",
]
