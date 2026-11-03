"""Safety-tested gesture session adapted from the wheel-lab 0.1.20 runtime."""

from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Event, RLock, Thread, current_thread
import time
from typing import Callable, Dict, Optional

from .engine import GestureConfig, GestureEngine, GestureMode, GestureRunner
from .geometry import Vec2, WheelModel
from .sinks import MotionFrame, PointerEventKind, RecordingSink

from .interlock import InputInterlock
from .auto_recognition import recognize_hovered_wheel
from .feedback_state import WheelFeedbackState
from .macos import DAVINCI_BUNDLE_ID, AppIdentity, MacOSBindings, PermissionState
from .passive_observer import PassiveWheelObserver
from .quartz_sink import (
    DEFAULT_EDGE_MARGIN,
    LOGICAL_DELTA_SCALE,
    RESOLVE_LOCATION_SCALE,
    REBASE_ANCHOR_DELAY,
    REBASE_MIN_ANCHOR_AFTER_WARP,
    REBASE_WARP_DELAY,
    QuartzGestureSink,
)
from .diagnostics import TraceBuffer
from .motion import CadenceGain
from .windows_sink import (
    WindowsGestureSink, WindowsInputInterlock, WINDOWS_LOCATION_SCALE,
    WINDOWS_EDGE_MARGIN,
)
from .windows import wait_for_windows_frame


RUNTIME_VERSION = "1.2.8"
LIVE_LOCATION_SCALE = RESOLVE_LOCATION_SCALE
# Real-host inner/outer drift validation passed with observed cursor origins.
# Retire the temporary high-frequency rebase test.
LIVE_EDGE_MARGIN = DEFAULT_EDGE_MARGIN
PASSIVE_OBSERVER_QUIET_DELAY = 0.18
MAX_HOST_INPUT_AMOUNT = 100000.0
WINDOWS_IDLE_RECALIBRATION_REASON = "windows_idle_visual_recalibration"


class WorkerError(RuntimeError):
    """Expected command error that is safe to return over NDJSON."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WorkerConfig:
    output_mode: str = "recording"
    # Effective amount per host callback. Orbit is divided by the Node adapter;
    # measured TourBox push/pull callbacks advance a fixed logical pixel each.
    orbit_step_deg: float = 1.0
    push_pull_step_px: float = 1.0
    speed_profile: str = "raw"
    invert_orbit: bool = False
    invert_push_pull: bool = False
    simulator: bool = False

    def as_dict(self) -> dict:
        return {
            "outputMode": self.output_mode,
            "orbitStepDeg": self.orbit_step_deg,
            "pushPullStepPx": self.push_pull_step_px,
            "speedProfile": self.speed_profile,
            "invertOrbit": self.invert_orbit,
            "invertPushPull": self.invert_push_pull,
            "simulator": self.simulator,
        }


@dataclass(frozen=True)
class Calibration:
    center: Optional[Vec2] = None
    handle: Optional[Vec2] = None
    rim: Optional[Vec2] = None
    source: str = "manual"
    confidence: Optional[float] = None
    diameter_axis: Optional[Vec2] = None
    signed_radius: Optional[float] = None
    diameter_last_side: Optional[int] = None
    last_nonzero_axis: Optional[Vec2] = None
    # Stable visible geometry, distinct from a learned effective motion clamp.
    visual_radius: Optional[float] = None

    def capture(self, point: str, position: Vec2) -> "Calibration":
        if point == "center":
            return Calibration(center=position, source="manual")
        if point == "handle":
            if self.center is None:
                raise WorkerError("capture_order", "capture center before handle")
            return Calibration(center=self.center, handle=position, source="manual")
        if point == "rim":
            if self.center is None or self.handle is None:
                raise WorkerError("capture_order", "capture center and handle before rim")
            return Calibration(
                center=self.center,
                handle=self.handle,
                rim=position,
                source="manual",
            )
        raise WorkerError("invalid_point", "point must be center, handle, or rim")

    def errors(self) -> list:
        problems = []
        if self.center is None:
            problems.append("center_not_captured")
        if self.handle is None:
            problems.append("handle_not_captured")
        if self.rim is None:
            problems.append("rim_not_captured")
        if problems:
            return problems
        assert self.center is not None and self.handle is not None and self.rim is not None
        values = (
            self.center.x,
            self.center.y,
            self.handle.x,
            self.handle.y,
            self.rim.x,
            self.rim.y,
        )
        if not all(math.isfinite(value) for value in values):
            problems.append("non_finite_coordinate")
            return problems
        max_radius = (self.rim - self.center).length
        handle_radius = (self.handle - self.center).length
        if max_radius < 8.0:
            problems.append("rim_too_close_to_center")
        if max_radius > 2000.0:
            problems.append("rim_implausibly_far_from_center")
        if handle_radius > max_radius + 2.0:
            problems.append("handle_outside_rim")
        return problems

    @property
    def valid(self) -> bool:
        return not self.errors()

    @property
    def max_radius(self) -> Optional[float]:
        if self.center is None or self.rim is None:
            return None
        return (self.rim - self.center).length

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors(),
            "center": _vec_dict(self.center),
            "handle": _vec_dict(self.handle),
            "rim": _vec_dict(self.rim),
            "maxRadius": self.max_radius,
            "nextPoint": self.next_point,
            "source": self.source,
            "confidence": self.confidence,
            "diameterAxis": _vec_dict(self.diameter_axis),
            "signedRadius": self.signed_radius,
            "diameterLastSide": self.diameter_last_side,
            "lastNonzeroAxis": _vec_dict(self.last_nonzero_axis),
        }

    @property
    def next_point(self) -> str:
        if self.center is None:
            return "center"
        if self.handle is None:
            return "handle"
        if self.rim is None:
            return "rim"
        return "complete"


class _ObservedRecordingSink(RecordingSink):
    def __init__(self, state_callback: Callable[[bool], None], trace_callback) -> None:
        super().__init__()
        self._state_callback = state_callback
        self._trace_callback = trace_callback

    def _trace(self, kind, position, timestamp, reason=""):
        self._trace_callback({"kind": kind, "position": _vec_dict(position),
                              "monotonic": timestamp, "reason": reason,
                              "clickState": 1, "ok": True, "recording": True})

    def down(self, position: Vec2, timestamp: float) -> None:
        super().down(position, timestamp)
        self._trace("down", position, timestamp)
        self._state_callback(True)

    def drag(self, position: Vec2, timestamp: float) -> None:
        super().drag(position, timestamp)
        self._trace("drag", position, timestamp)

    def drag_frame(self, frame: MotionFrame) -> None:
        super().drag_frame(frame)
        self._trace_callback({
            "kind": "drag",
            "position": _vec_dict(frame.logical_after),
            "monotonic": frame.timestamp,
            "reason": "gesture_update",
            "clickState": 1,
            "ok": True,
            "recording": True,
            "logical": {
                "mode": frame.mode,
                "before": _vec_dict(frame.logical_before),
                "after": _vec_dict(frame.logical_after),
                "applied": frame.logical_applied,
                "purpose": frame.purpose,
                "clamped": frame.clamped,
                "crossedCenter": frame.crossed_center,
            },
        })

    def observe_motion_frame(self, frame: MotionFrame) -> None:
        """Forward clamp metadata without recording a pointer DRAG."""

        super().observe_motion_frame(frame)
        self._trace_callback({
            "kind": "motion_observed",
            "position": _vec_dict(frame.logical_after),
            "monotonic": frame.timestamp,
            "reason": "clamped_zero_displacement",
            "ok": True,
            "recording": True,
            "postedMouseEvent": False,
            "logical": {
                "mode": frame.mode,
                "before": _vec_dict(frame.logical_before),
                "after": _vec_dict(frame.logical_after),
                "applied": frame.logical_applied,
                "clamped": frame.clamped,
                "crossedCenter": frame.crossed_center,
            },
        })

    def up(self, position: Vec2, timestamp: float, reason: str = "idle") -> None:
        super().up(position, timestamp, reason)
        self._trace("up", position, timestamp, reason)
        self._state_callback(False)


class WheelWorkerController:
    """Fail-closed worker state machine; defaults to recording and disarmed."""

    def __init__(
        self,
        bindings: Optional[MacOSBindings] = None,
        clock: Callable[[], float] = time.monotonic,
        emit_event: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._bindings = bindings or MacOSBindings()
        self._clock = clock
        self._emit_event = emit_event or (lambda _event: None)
        self._lock = RLock()
        self._cancel_lock = RLock()
        self._config = WorkerConfig()
        self._calibration = Calibration()
        self._state = "disarmed"
        self._last_cancel_reason = "startup_disarmed"
        self._windows_idle_recalibration = None
        self._locked_pid: Optional[int] = None
        self._locked_display_bounds = None
        self._engine: Optional[GestureEngine] = None
        self._runner: Optional[GestureRunner] = None
        self._sink = None
        self._recording_sink: Optional[_ObservedRecordingSink] = None
        self._interlock: Optional[InputInterlock] = None
        self._observer: Optional[PassiveWheelObserver] = None
        self._last_observer: Optional[PassiveWheelObserver] = None
        self._retired_observer: Optional[PassiveWheelObserver] = None
        self._last_observer_status: Optional[dict] = None
        self._feedback_state: Optional[WheelFeedbackState] = None
        self._last_feedback_status: Optional[dict] = None
        self._last_auto_recognition: Optional[dict] = None
        self._event_tap = None
        self._safety_stop: Optional[Event] = None
        self._safety_thread: Optional[Thread] = None
        self._retired_runner: Optional[GestureRunner] = None
        self._retired_sink: Optional[QuartzGestureSink] = None
        self._cleanup_thread: Optional[Thread] = None
        self._shutdown = False
        self._synthetic_calibration = False
        self._generation = 0
        self._cadence = CadenceGain()
        self._trace = TraceBuffer(self._emit_event, clock=self._clock)
        self._session_id = None
        self._last_session = None
        self._last_mouse_down_at = None
        self._gesture_timing = {}

    def configure(self, payload: dict) -> dict:
        # Arm holds the same serial lock across its one-shot screenshot and
        # publication.  A settings update arriving through a direct controller
        # caller therefore cannot observe the temporary ``disarmed`` state and
        # publish a configuration which disagrees with the newly built engine.
        # (The normal NDJSON protocol is serial too; this also makes the public
        # controller API safe for tests and alternate hosts.)
        with self._cancel_lock:
            return self._configure_serial(payload)

    def _configure_serial(self, payload: dict) -> dict:
        output_mode = payload.get("outputMode", self._config.output_mode)
        if output_mode not in ("recording", "live"):
            raise WorkerError("invalid_config", "outputMode must be recording or live")
        speed_profile = payload.get("speedProfile", self._config.speed_profile)
        if speed_profile not in ("raw", "tourbox_like"):
            raise WorkerError("invalid_config", "speedProfile must be raw or tourbox_like")
        orbit_step = _positive_number(
            payload.get("orbitStepDeg", self._config.orbit_step_deg),
            "orbitStepDeg",
            maximum=30.0,
        )
        radial_step = _positive_number(
            payload.get("pushPullStepPx", self._config.push_pull_step_px),
            "pushPullStepPx",
            maximum=50.0,
        )
        new_config = WorkerConfig(
            output_mode=output_mode,
            orbit_step_deg=orbit_step,
            push_pull_step_px=radial_step,
            speed_profile=speed_profile,
            # Inversion is performed by the Node action layer.  These values
            # are retained for status/UI only and are never re-applied here.
            invert_orbit=bool(payload.get("invertOrbit", self._config.invert_orbit)),
            invert_push_pull=bool(
                payload.get("invertPushPull", self._config.invert_push_pull)
            ),
            simulator=bool(payload.get("simulator", self._config.simulator)),
        )
        with self._lock:
            changed = new_config != self._config
            active = self._state != "disarmed"
        if changed and active:
            self.cancel("configuration_changed")
        with self._lock:
            self._config = new_config
        return {"config": new_config.as_dict(), "disarmed": changed and active}

    def capture(self, point: str) -> dict:
        self.cancel("calibration_capture")
        try:
            x, y = self._bindings.current_mouse_position()
        except Exception as exc:
            raise WorkerError("capture_failed", str(exc)) from exc
        position = Vec2(float(x), float(y))
        with self._lock:
            self._calibration = self._calibration.capture(point, position)
            calibration = self._calibration.as_dict()
        return {"captured": point, "position": _vec_dict(position), "calibration": calibration}

    def preflight(self) -> dict:
        available = bool(getattr(self._bindings, "available", False))
        unavailable_reason = str(getattr(self._bindings, "unavailable_reason", ""))
        permissions = PermissionState(False, False, False)
        app = AppIdentity(None, "", "")
        mouse = None
        left_down = None
        if available:
            try:
                permissions = self._bindings.permissions()
            except Exception:
                pass
            try:
                app = self._bindings.frontmost_app()
            except Exception:
                pass
            try:
                x, y = self._bindings.current_mouse_position()
                mouse = {"x": x, "y": y}
            except Exception:
                pass
            try:
                left_down = bool(self._bindings.left_button_down())
            except Exception:
                pass
        with self._lock:
            calibration = self._calibration.as_dict()
            simulator = self._config.simulator
            last_auto_recognition = (
                dict(self._last_auto_recognition)
                if self._last_auto_recognition is not None
                else None
            )
        event_tap_supported = available and hasattr(self._bindings, "start_event_tap")
        observer_supported = available and self._passive_observer_supported()
        auto_recognition_supported = available and self._auto_recognition_supported()
        screen_capture_allowed = None
        if observer_supported:
            try:
                screen_capture_allowed = bool(self._bindings.screen_capture_allowed())
            except Exception:
                screen_capture_allowed = None
        live_blockers = []
        if simulator:
            live_blockers.append("simulator_recording_only")
        if not available:
            live_blockers.append("platform_unavailable")
        if not permissions.ready:
            live_blockers.append("permissions_not_ready")
        if not app.is_davinci:
            live_blockers.append("davinci_not_frontmost")
        if left_down is not False:
            live_blockers.append("left_button_not_released")
        handle = calibration.get("handle")
        manual_pointer_ready = not (
            mouse is None
            or handle is None
            or math.hypot(mouse["x"] - handle["x"], mouse["y"] - handle["y"]) > 3.0
        )
        manual_ready = bool(calibration["valid"] and manual_pointer_ready)
        auto_ready = bool(
            auto_recognition_supported and screen_capture_allowed is True
        )
        if not auto_ready and not manual_ready:
            if not calibration["valid"]:
                live_blockers.append("calibration_invalid")
            else:
                live_blockers.append("pointer_not_on_handle")
            if auto_recognition_supported and screen_capture_allowed is not True:
                live_blockers.append("screen_capture_permission_unavailable")
        if not event_tap_supported:
            live_blockers.append("event_tap_unsupported")
        return {
            "platformAvailable": available,
            "unavailableReason": unavailable_reason,
            "permissions": {
                "accessibility": permissions.accessibility,
                "listenEvents": permissions.listen_events,
                "postEvents": permissions.post_events,
                "ready": permissions.ready,
            },
            "frontmost": {
                "pid": app.pid,
                "bundleId": app.bundle_id,
                "executablePath": app.executable_path,
                "isDaVinciResolve": app.is_davinci,
                "expectedBundleId": DAVINCI_BUNDLE_ID,
            },
            "mouse": mouse,
            "leftButtonDown": left_down,
            "eventTapSupported": event_tap_supported,
            "observer": {
                "mode": "passive",
                "supported": observer_supported,
                "screenRecording": screen_capture_allowed,
                "requiredForLive": False,
                "requiredForAutoRecognition": True,
                "activeFeedback": True,
                "quietDelayMs": PASSIVE_OBSERVER_QUIET_DELAY * 1000.0,
            },
            "autoRecognition": {
                "supported": auto_recognition_supported,
                "screenRecording": screen_capture_allowed,
                "canAttempt": auto_ready,
                "trigger": "arm_boundary",
                "selection": "hovered_wheel",
                "captureCountPerAttempt": 1,
                "lastResult": last_auto_recognition,
                "manualFallbackReady": manual_ready,
            },
            "simulator": simulator,
            "liveAllowed": not live_blockers,
            "liveBlockers": live_blockers,
            "calibration": calibration,
        }

    def request_permissions(self) -> dict:
        """Request missing macOS permissions without weakening Live gates."""

        if not bool(getattr(self._bindings, "available", False)):
            reason = str(getattr(self._bindings, "unavailable_reason", ""))
            raise WorkerError(
                "platform_unavailable",
                reason or "macOS permission APIs are unavailable",
            )
        requester = getattr(self._bindings, "request_permissions", None)
        if not callable(requester):
            raise WorkerError(
                "permission_request_unavailable",
                "macOS permission request APIs are unavailable",
            )

        # Opening a TCC prompt or System Settings necessarily changes focus.
        # Release any owned mouse state before requesting it.
        self.cancel("permission_request")
        try:
            request = requester()
        except Exception as exc:
            raise WorkerError("permission_request_failed", str(exc)) from exc
        screen_request = {
            "requested": False,
            "before": None,
            "after": None,
            "requestReturned": False,
            "error": "screen capture request API is unavailable",
        }
        screen_requester = getattr(
            self._bindings, "request_screen_capture_access", None
        )
        if callable(screen_requester):
            try:
                screen_request = screen_requester()
            except Exception as exc:
                screen_request = {
                    **screen_request,
                    "error": str(exc),
                }
        report = self.preflight()
        screen_needs_restart = bool(
            screen_request.get("requested") and not screen_request.get("after")
        )
        return {
            "request": request,
            "screenCaptureRequest": screen_request,
            "permissions": report["permissions"],
            "observer": report["observer"],
            "ready": report["permissions"]["ready"],
            "needsRestart": bool(
                (
                    any(request.get("requested", {}).values())
                    and not report["permissions"]["ready"]
                )
                or screen_needs_restart
            ),
        }

    def toggle_arm(self) -> dict:
        with self._lock:
            active = self._state != "disarmed"
        if active:
            stopped = self.cancel("manual_stop")
            return {
                "armed": False,
                "state": stopped.get("state", "disarmed"),
                "reason": "manual_stop",
                "cleanupPending": bool(stopped.get("cleanupPending")),
            }
        return self.arm()

    def arm(self) -> dict:
        with self._cancel_lock:
            return self._arm_serial()

    def _arm_serial(self) -> dict:
        with self._lock:
            if self._shutdown:
                raise WorkerError("shutdown", "worker is shutting down")
            cleanup_thread = self._cleanup_thread
            if (
                self._retired_runner is not None
                or self._retired_sink is not None
                or (cleanup_thread is not None and cleanup_thread.is_alive())
            ):
                raise WorkerError(
                    "cleanup_pending",
                    "the previous mouse session is still being safely released",
                )
            calibration = self._calibration
            config = self._config
            if self._state != "disarmed":
                return {"armed": True, "state": self._state}
        interval = 0.5
        if config.output_mode == "live":
            try:
                reported = float(self._bindings.double_click_interval())
                if math.isfinite(reported) and 0.05 <= reported <= 5.0:
                    interval = reported
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
        engine_config = self._engine_config(
            config.speed_profile,
            interval,
            live=config.output_mode == "live",
        )
        self._cadence.reset()
        self._session_id = "wheel-%d-%d" % (time.time_ns(), self._generation + 1)
        self._gesture_timing = {"idleTimeoutMs": engine_config.idle_timeout * 1000,
                                "minDownIntervalMs": engine_config.min_down_interval * 1000,
                                "doubleClickIntervalMs": interval * 1000}
        self._trace.start()
        if config.output_mode == "recording":
            problems = calibration.errors()
            if problems:
                model = WheelModel(Vec2(0.0, 0.0), Vec2(50.0, 0.0), 100.0)
                synthetic_calibration = True
            else:
                assert calibration.center is not None and calibration.handle is not None
                assert calibration.max_radius is not None
                model = WheelModel(
                    calibration.center, calibration.handle, calibration.max_radius
                )
                synthetic_calibration = False
            sink = _ObservedRecordingSink(self._on_pointer_state, self._record_pointer)
            engine = GestureEngine(model, sink, engine_config, clock=self._clock)
            runner = GestureRunner(engine, clock=self._clock)
            try:
                runner.start()
            except Exception as exc:
                raise WorkerError("runner_start_failed", str(exc)) from exc
            with self._lock:
                self._sink = sink
                self._recording_sink = sink
                self._engine = engine
                self._runner = runner
                self._observer = None
                self._last_observer = None
                self._last_observer_status = None
                self._feedback_state = None
                self._last_feedback_status = None
                self._state = "armed"
                self._last_cancel_reason = ""
                self._windows_idle_recalibration = None
                self._synthetic_calibration = synthetic_calibration
                self._generation += 1
            self._emit_status("armed")
            return {
                "armed": True,
                "state": "armed",
                "outputMode": "recording",
                "syntheticCalibration": synthetic_calibration,
            }

        if config.simulator:
            raise WorkerError(
                "live_preflight_failed",
                "Simulator is recording-only; live mouse output is disabled",
            )
        calibration = self._resolve_live_calibration(calibration)
        problems = calibration.errors()
        if problems:
            raise WorkerError("calibration_invalid", ", ".join(problems))
        assert calibration.center is not None and calibration.handle is not None
        assert calibration.max_radius is not None
        model = WheelModel(calibration.center, calibration.handle, calibration.max_radius)
        self._arm_live(model, engine_config, calibration.handle)
        self._emit_status("armed")
        with self._lock:
            return {
                "armed": True,
                "state": self._state,
                "outputMode": "live",
                "lockedPid": self._locked_pid,
                "calibrationSource": calibration.source,
            }

    def _resolve_live_calibration(self, fallback: Calibration) -> Calibration:
        """Recognise the wheel under the cursor once, with manual fallback.

        This runs only on the explicit Arm boundary. It is intentionally
        synchronous here so no pointer event can begin against uncertain
        geometry; all later visual checks run asynchronously.
        """

        initial = self.preflight()
        setup_failures = self._live_setup_failures(initial)
        if setup_failures:
            raise WorkerError("live_preflight_failed", "; ".join(setup_failures))
        initial_pid = initial["frontmost"]["pid"]

        fallback_ready = False
        if fallback.valid and fallback.handle is not None:
            try:
                mouse_x, mouse_y = self._bindings.current_mouse_position()
                fallback_ready = math.hypot(
                    float(mouse_x) - fallback.handle.x,
                    float(mouse_y) - fallback.handle.y,
                ) <= 3.0
            except Exception:
                fallback_ready = False

        if not self._auto_recognition_supported():
            # Older/fake bindings retain the established three-point flow.
            return fallback

        recognition = recognize_hovered_wheel(self._bindings)
        recognition_status = recognition.to_dict()
        with self._lock:
            self._last_auto_recognition = recognition_status
        self._trace.record(
            {
                "event": "auto_recognition",
                "sessionId": self._session_id,
                "outputMode": "live",
                **recognition_status,
            }
        )
        if not recognition.ok or recognition.calibration is None:
            if fallback_ready:
                return fallback
            reason = recognition.reason or "unknown"
            detail = recognition.detail or "hover the pointer inside the target color wheel"
            raise WorkerError(
                "auto_recognition_failed",
                "%s: %s; grant Screen Recording or use manual 3-point calibration"
                % (reason, detail),
            )

        found = recognition.calibration
        calibration = Calibration(
            center=Vec2(*found.center),
            handle=Vec2(*found.handle),
            rim=Vec2(*found.rim),
            source="hover-one-shot",
            confidence=float(found.confidence),
        )
        problems = calibration.errors()
        if problems:
            raise WorkerError(
                "auto_recognition_failed",
                "recognized geometry is unsafe: %s" % ", ".join(problems),
            )
        assert calibration.handle is not None
        second = self.preflight()
        setup_failures = self._live_setup_failures(second)
        if second["frontmost"]["pid"] != initial_pid:
            setup_failures.append("frontmost DaVinci process changed during recognition")
        if setup_failures:
            raise WorkerError("live_preflight_failed", "; ".join(setup_failures))
        second_mouse = second.get("mouse")
        if second_mouse is None or math.hypot(
            float(second_mouse["x"]) - calibration.center.x,
            float(second_mouse["y"]) - calibration.center.y,
        ) > float(found.visual_radius) + 2.0:
            # The Arm-time hover chooses the wheel.  If the pointer moved to a
            # different wheel while the one permitted screenshot was being
            # analysed, never warp it back to the stale selection.
            raise WorkerError(
                "auto_recognition_hover_changed",
                "the pointer left the recognized wheel during recognition; hover the target wheel and arm again",
            )
        try:
            self._bindings.warp_mouse_cursor(
                (calibration.handle.x, calibration.handle.y)
            )
            mouse_x, mouse_y = self._bindings.current_mouse_position()
        except Exception as exc:
            raise WorkerError(
                "auto_recognition_failed",
                "recognized the wheel but could not place the pointer on its handle: %s"
                % exc,
            ) from exc
        if math.hypot(
            float(mouse_x) - calibration.handle.x,
            float(mouse_y) - calibration.handle.y,
        ) > 3.0:
            raise WorkerError(
                "auto_recognition_failed",
                "recognized the wheel but the pointer did not reach its handle",
            )
        with self._lock:
            self._calibration = calibration
        return calibration

    @staticmethod
    def _live_setup_failures(report: dict) -> list:
        """Return non-geometry gates that must hold before any cursor warp."""

        failures = []
        if report.get("simulator"):
            failures.append("Simulator is recording-only; live mouse output is disabled")
        if not report.get("platformAvailable"):
            failures.append(report.get("unavailableReason") or "macOS APIs unavailable")
        if not (report.get("permissions") or {}).get("ready"):
            failures.append(
                "Accessibility, Input Monitoring, and post-event permissions are required"
            )
        if not (report.get("frontmost") or {}).get("isDaVinciResolve"):
            failures.append("DaVinci Resolve must be frontmost")
        if report.get("leftButtonDown") is not False:
            failures.append("left mouse button must be released")
        if not report.get("eventTapSupported"):
            failures.append("listen-only event tap is unavailable")
        return failures

    def _arm_live(
        self,
        model: WheelModel,
        engine_config: GestureConfig,
        handle: Vec2,
    ) -> None:
        windows = getattr(self._bindings, "platform_name", None) == "Windows"
        sink_class = WindowsGestureSink if windows else QuartzGestureSink
        interlock_class = WindowsInputInterlock if windows else InputInterlock
        location_scale = WINDOWS_LOCATION_SCALE if windows else LIVE_LOCATION_SCALE
        report = self.preflight()
        failures = []
        if self._config.simulator:
            failures.append("Simulator is recording-only; live mouse output is disabled")
        if not report["platformAvailable"]:
            failures.append(report["unavailableReason"] or "macOS APIs unavailable")
        if not report["permissions"]["ready"]:
            failures.append("Accessibility, Input Monitoring, and post-event permissions are required")
        if not report["frontmost"]["isDaVinciResolve"]:
            failures.append("DaVinci Resolve must be frontmost")
        if report["leftButtonDown"] is not False:
            failures.append("left mouse button must be released")
        mouse = report.get("mouse")
        if mouse is None or math.hypot(mouse["x"] - handle.x, mouse["y"] - handle.y) > 3.0:
            failures.append("move the pointer back onto the captured handle before arming")
        if not report["eventTapSupported"]:
            failures.append("listen-only event tap is unavailable")
        if failures:
            raise WorkerError("live_preflight_failed", "; ".join(failures))

        locked_pid = report["frontmost"]["pid"]
        display_resolver = getattr(
            self._bindings, "display_bounds_for_point", None
        )
        if not callable(display_resolver):
            raise WorkerError(
                "display_bounds_failed",
                "cannot establish safe mouse bounds: binding is unavailable",
            )
        try:
            display_bounds = display_resolver((handle.x, handle.y))
        except Exception as exc:
            raise WorkerError(
                "display_bounds_failed",
                "cannot establish safe mouse bounds: %s" % exc,
            ) from exc
        logical_bounds = (
            model.center.x - model.max_radius,
            model.center.y - model.max_radius,
            2.0 * model.max_radius,
            2.0 * model.max_radius,
        )
        try:
            sink_class.calculate_location_scale(
                location_scale,
                handle,
                display_bounds,
                logical_bounds,
                LIVE_EDGE_MARGIN,
            )
        except (TypeError, ValueError) as exc:
            raise WorkerError(
                "pointer_geometry_unsafe",
                "wheel geometry cannot use edge rebasing safely: %s" % exc,
            ) from exc
        session_id = self._session_id
        next_generation = self._generation + 1
        interlock = interlock_class(
            (handle.x, handle.y), target_pid=locked_pid,
            trace_callback=lambda event: self._trace.record(
                {"sessionId": session_id, "outputMode": "live", **event}
            ),
        )
        try:
            event_tap = self._bindings.start_event_tap(interlock.handle_event)
        except Exception as exc:
            raise WorkerError("event_tap_failed", str(exc)) from exc

        sink = None
        engine = None
        runner = None
        observer = None
        with self._lock:
            calibration = self._calibration
        center_axis = (
            calibration.rim - calibration.center
            if calibration.rim is not None and calibration.center is not None
            else None
        )
        seeded_center_axis = bool(
            model.radius <= 1e-9
            and center_axis is not None
            and center_axis.length > 1e-6
            and model.last_nonzero_axis.dot(center_axis.normalized()) >= 1.0 - 1e-6
        )
        feedback = WheelFeedbackState(
            model.center,
            handle,
            model.max_radius,
            orbit_path_recovery=engine_config.orbit_alignment_step > 0.0,
            preserve_initial_diameter_axis=bool(
                (
                    calibration.diameter_axis is not None
                    and calibration.signed_radius is not None
                )
                or seeded_center_axis
            ),
        )
        observer_setup_error = ""
        published = False
        try:
            # Re-check every mutable gate after the tap is ready; no event may
            # be posted in the interval between the two checks.
            second = self.preflight()
            second_mouse = second.get("mouse")
            if not second["permissions"]["ready"]:
                raise WorkerError("live_preflight_failed", "permissions changed while arming")
            if second["frontmost"]["pid"] != locked_pid or not second["frontmost"]["isDaVinciResolve"]:
                raise WorkerError("live_preflight_failed", "frontmost DaVinci process changed while arming")
            if second["leftButtonDown"] is not False:
                raise WorkerError("live_preflight_failed", "left mouse button became pressed while arming")
            if second_mouse is None or math.hypot(
                second_mouse["x"] - handle.x, second_mouse["y"] - handle.y
            ) > 3.0:
                raise WorkerError("live_preflight_failed", "pointer moved while arming")
            if not event_tap.alive:
                raise WorkerError("event_tap_failed", event_tap.error or "event tap stopped")

            # Keep the safety target lock in InputInterlock, but post through
            # the HID/session route. On the real host CGEventPostToPid returns
            # successfully while bypassing the session event tap, which makes
            # tagged delivery impossible to confirm and must fail closed.
            sink = sink_class(
                self._bindings,
                interlock,
                state_callback=self._on_pointer_state,
                clock=self._clock,
                trace_callback=self._record_pointer,
                location_scale=location_scale,
                display_bounds=display_bounds,
                logical_bounds=logical_bounds,
                initial_anchor=handle,
                edge_margin=LIVE_EDGE_MARGIN,
                detach_cursor=True,
                observe_rebase_origin=True,
            )
            engine = GestureEngine(model, sink, engine_config, clock=self._clock,
                                   last_down_at=self._last_mouse_down_at)
            runner = GestureRunner(
                engine, clock=self._clock,
                wait_fn=wait_for_windows_frame if windows else None,
            )
            observer_supported = self._passive_observer_supported()
            retired_observer_alive = False
            with self._lock:
                retired_observer = self._retired_observer
            if retired_observer is not None:
                try:
                    retired_observer_alive = bool(
                        retired_observer.status().get("alive")
                    )
                except Exception:
                    # Unknown means unsafe to start another screenshot daemon.
                    retired_observer_alive = True
                if not retired_observer_alive:
                    with self._lock:
                        if self._retired_observer is retired_observer:
                            self._retired_observer = None
            if observer_supported and retired_observer_alive:
                observer_setup_error = "previous_observer_still_alive"
                observer_supported = False
            if observer_supported:
                try:
                    observer = PassiveWheelObserver(
                        self._bindings,
                        center=model.center,
                        max_radius=model.max_radius,
                        session_id=session_id,
                        generation=next_generation,
                        snapshot_provider=engine.snapshot,
                        trace_callback=lambda event: self._trace.record(
                            {
                                "event": "wheel_observation",
                                "sessionId": session_id,
                                "outputMode": "live",
                                **event,
                            }
                        ),
                        result_callback=lambda result: self._apply_visual_feedback(
                            result,
                            engine=engine,
                            feedback=feedback,
                            generation=next_generation,
                            session_id=session_id,
                        ),
                        clock=self._clock,
                        quiet_delay=PASSIVE_OBSERVER_QUIET_DELAY,
                        idle_only=windows,
                        numeric_capture=getattr(self, "_numeric_capture", None),
                        display_bounds=display_bounds,
                    )
                except Exception as exc:
                    # Visual correction is fail-soft. Invalid or oversized
                    # geometry must never weaken or block live control.
                    observer_setup_error = str(exc)
            safety_stop = Event()
            runner.start()
            with self._lock:
                self._generation = next_generation
                generation = next_generation
                safety_thread = Thread(
                    target=self._safety_loop,
                    args=(safety_stop, generation),
                    name="wheel-safety-watchdog",
                    daemon=True,
                )
                self._sink = sink
                self._recording_sink = None
                self._engine = engine
                self._runner = runner
                self._interlock = interlock
                self._observer = observer
                self._feedback_state = feedback
                self._last_feedback_status = None
                self._last_observer = None
                self._last_observer_status = (
                    {
                        "mode": "passive",
                        "observerOnly": False,
                        "started": False,
                        "closed": True,
                        "alive": False,
                        "lastError": "observer_setup_failed:%s"
                        % observer_setup_error,
                        "sessionId": session_id,
                        "generation": next_generation,
                    }
                    if observer_setup_error
                    else None
                )
                self._event_tap = event_tap
                self._safety_stop = safety_stop
                self._safety_thread = safety_thread
                self._locked_pid = int(locked_pid)
                self._locked_display_bounds = tuple(display_bounds)
                self._state = "armed"
                self._last_cancel_reason = ""
                self._windows_idle_recalibration = None
                self._synthetic_calibration = False
                published = True
            if observer_setup_error:
                self._trace.record(
                    {
                        "event": "wheel_observation",
                        "kind": "passive_observer",
                        "phase": "setup",
                        "result": "failed",
                        "reason": "observer_setup_failed",
                        "detail": observer_setup_error,
                        "sessionId": session_id,
                        "generation": next_generation,
                        "outputMode": "live",
                        "observerOnly": False,
                    }
                )
            if observer is not None:
                try:
                    observer.start(handle)
                except Exception as exc:
                    try:
                        observer.close("observer_start_failed")
                    except Exception:
                        pass
                    failed_status = {
                        "mode": "passive",
                        "observerOnly": False,
                        "started": False,
                        "closed": True,
                        "alive": False,
                        "lastError": "observer_start_failed:%s" % exc,
                        "sessionId": session_id,
                        "generation": generation,
                    }
                    with self._lock:
                        if self._observer is observer:
                            self._observer = None
                            self._last_observer_status = failed_status
                    self._trace.record(
                        {
                            "event": "wheel_observation",
                            "kind": "passive_observer",
                            "phase": "start",
                            "result": "failed",
                            "reason": "observer_start_failed",
                            "detail": str(exc),
                            "sessionId": session_id,
                            "generation": generation,
                            "outputMode": "live",
                            "observerOnly": False,
                        }
                    )
                    observer = None
            safety_thread.start()
        except Exception:
            # Arm rollback follows the same safety ordering as normal cancel.
            # In particular, a timed-out native post must not make rollback
            # release its source or synchronously enter engine.cancel.
            if isinstance(sink, QuartzGestureSink):
                sink.request_stop("arm_failed")
            if runner is not None:
                runner.request_stop()
            arm_release_ok = True
            if isinstance(sink, QuartzGestureSink):
                try:
                    arm_release_ok = sink.emergency_release("arm_failed")
                except Exception:
                    arm_release_ok = False
            runner_stopped = True
            if runner is not None:
                try:
                    runner_stopped = runner.stop(timeout=0.75, cancel=True)
                except Exception:
                    runner_stopped = False
            sink_closed = True
            if isinstance(sink, QuartzGestureSink):
                try:
                    sink_closed = sink.close(blocking=runner_stopped)
                except Exception:
                    sink_closed = False
            arm_observer_status = None
            if observer is not None:
                try:
                    observer.close("arm_failed")
                except Exception:
                    pass
                try:
                    arm_observer_status = observer.status()
                except Exception:
                    arm_observer_status = {
                        "mode": "passive",
                        "closed": True,
                        "alive": True,
                        "lastError": "observer_status_failed",
                    }
            event_tap.stop()
            cleanup_needed = bool(
                runner is not None
                and (
                    not runner_stopped
                    or (isinstance(sink, QuartzGestureSink) and not sink_closed)
                )
            )
            cleanup_thread = None
            with self._lock:
                if not published or self._sink is sink:
                    if published:
                        self._engine = None
                        self._runner = None
                        self._sink = None
                        self._recording_sink = None
                        self._interlock = None
                        self._observer = None
                        if self._feedback_state is feedback:
                            self._last_feedback_status = feedback.status()
                            self._feedback_state = None
                        self._event_tap = None
                        self._safety_stop = None
                        self._safety_thread = None
                        self._locked_pid = None
                        self._locked_display_bounds = None
                    if observer is not None:
                        self._last_observer = observer
                    if arm_observer_status is not None:
                        self._last_observer_status = arm_observer_status
                        if bool(arm_observer_status.get("alive")):
                            self._retired_observer = observer
                    if cleanup_needed:
                        self._retired_runner = runner
                        self._retired_sink = (
                            sink if isinstance(sink, QuartzGestureSink) else None
                        )
                        cleanup_thread = Thread(
                            target=self._reap_cancelled_session,
                            args=(
                                runner,
                                sink,
                                engine,
                                None,
                                interlock,
                                session_id,
                                "arm_failed",
                                arm_release_ok,
                            ),
                            name="wheel-arm-rollback-reaper",
                            daemon=True,
                        )
                        self._cleanup_thread = cleanup_thread
                        self._state = "cleanup_pending"
                    else:
                        self._state = "disarmed"
                    self._synthetic_calibration = False
            if cleanup_thread is not None:
                cleanup_thread.start()
            raise

    def input(self, payload: dict) -> dict:
        # Do not hold the cancellation mutex while entering the engine.  A
        # runner can be stuck in a synchronous native post while holding the
        # engine lock; the emergency path must still reach its bounded join
        # and quarantine logic.  Generation/state are revalidated below after
        # ``engine.add`` returns.
        return self._input_serial(payload)

    def _input_serial(self, payload: dict) -> dict:
        mode = payload.get("mode")
        if mode not in ("orbit", "push_pull"):
            raise WorkerError("invalid_input", "mode must be orbit or push_pull")
        direction_raw = payload.get("direction")
        if isinstance(direction_raw, bool):
            raise WorkerError("invalid_input", "direction must be -1 or 1")
        try:
            direction = float(direction_raw)
        except (TypeError, ValueError):
            raise WorkerError("invalid_input", "direction must be -1 or 1")
        if direction not in (-1.0, 1.0):
            raise WorkerError("invalid_input", "direction must be -1 or 1")

        with self._lock:
            if self._state not in ("armed", "dragging") or self._engine is None:
                raise WorkerError("not_armed", "arm the worker before sending input")
            engine = self._engine
            generation = self._generation
            interlock = self._interlock
            observer = self._observer
            configured_profile = self._config.speed_profile
            fallback = (
                self._config.orbit_step_deg
                if mode == "orbit"
                else self._config.push_pull_step_px
            )
        # A host callback is one cadence sample even when it contains a large
        # tick batch. The 120 Hz engine already slices the accumulated delta;
        # clipping here would either lose motion or tempt callers to resample
        # the same callback and incorrectly accelerate its later chunks.
        amount = _positive_number(
            payload.get("amount", fallback),
            "amount",
            maximum=MAX_HOST_INPUT_AMOUNT,
        )
        if interlock is not None:
            reason = interlock.watchdog_reason(self._clock())
            if reason:
                self.cancel(reason)
                raise WorkerError("safety_cancelled", reason)

        # Node applies inversion once. Acceleration has no output-side momentum.
        now = self._clock()
        effective_profile = (
            "raw"
            if bool(payload.get("disableCadence"))
            else self._effective_speed_profile(configured_profile, mode)
        )
        cadence = self._cadence.sample(
            effective_profile, mode, direction, payload.get("context"), now
        )
        magnitude = amount * cadence["gain"]
        cadence["cadenceGain"] = cadence["gain"]
        cadence["gain"] = magnitude / amount
        delta = direction * magnitude
        self._trace.record({"event": "input", "sessionId": self._session_id,
                            "outputMode": self._config.output_mode, "monotonic": now,
                            "mode": mode, "direction": direction, "baseAmount": amount,
                            # Keep ``profile`` as the configured value for old
                            # trace readers; the explicit pair below records
                            # which curve was actually applied to this mode.
                            "delta": delta, "profile": configured_profile,
                            "configuredProfile": configured_profile,
                            "effectiveProfile": effective_profile,
                            "hostRotateEvent": payload.get("hostRotateEvent"),
                            "tuningVersion": payload.get("tuningVersion"),
                            "rawEventsPerDetent": payload.get("rawEventsPerDetent"),
                            "rawEventWeight": payload.get("rawEventWeight"),
                            "appliedEventWeight": payload.get("appliedEventWeight"),
                            "perDetentAmount": payload.get("perDetentAmount"),
                            "perHostEventAmount": payload.get("perHostEventAmount"),
                            **cadence})
        if getattr(self._bindings, "platform_name", None) == "Windows":
            # Idle visual retirement uses this same lock before closing the
            # generation. An input which loses that race must remain unqueued
            # so the backend can replay it once after fresh recognition.
            with engine._lock:
                self._validate_input_generation(engine, generation)
                engine.add(mode, delta, now=now,
                           orbit_frame_scale=cadence["orbitFrameScale"],
                           radial_frame_scale=cadence["radialFrameScale"])
        else:
            engine.add(mode, delta, now=now,
                       orbit_frame_scale=cadence["orbitFrameScale"],
                       radial_frame_scale=cadence["radialFrameScale"])
        self._validate_input_generation(engine, generation)
        if observer is not None:
            try:
                observer.note_input(mode, fresh_required=engine.snapshot().fresh_handle_required)
            except Exception:
                # Visual scheduling is fail-soft. It cannot turn an accepted
                # encoder event into a failed input operation.
                pass
        return {
            "accepted": True,
            "mode": mode,
            "delta": delta,
            "gain": cadence["gain"],
            "statistics": self.statistics(),
        }

    def _validate_input_generation(self, engine, generation):
        with self._lock:
            if (
                self._generation != generation
                or self._engine is not engine
                or self._state not in ("armed", "dragging")
            ):
                # The stop gate is already closed, so this queued delta cannot
                # create a new frame.  Report the race instead of claiming the
                # encoder event was accepted by an active session.
                recovery = self._windows_idle_recalibration
                if (recovery is not None and recovery["generation"] == generation
                        and self._last_cancel_reason == WINDOWS_IDLE_RECALIBRATION_REASON):
                    raise WorkerError("not_armed", WINDOWS_IDLE_RECALIBRATION_REASON)
                raise WorkerError("safety_cancelled", "the session was cancelled during input")

    @staticmethod
    def _effective_speed_profile(configured_profile: str, mode: str) -> str:
        """Give push/pull a mild curve without changing orbit or raw input."""

        if mode == "push_pull" and configured_profile == "tourbox_like":
            return "push_pull_mild"
        return configured_profile

    def cancel(self, reason: str = "cancel") -> dict:
        emergency = self._begin_emergency(reason)
        with self._cancel_lock:
            return self._cancel_serial(reason, emergency=emergency)

    def _cancel_generation(self, reason: str, generation: int) -> dict:
        emergency = self._begin_emergency(reason, expected_generation=generation)
        with self._cancel_lock:
            return self._cancel_serial(
                reason,
                expected_generation=generation,
                emergency=emergency,
            )

    def _begin_emergency(
        self,
        reason: str,
        expected_generation: Optional[int] = None,
    ) -> dict:
        """Gate motion and attempt UP before waiting for ``_cancel_lock``.

        An input callback may hold ``_cancel_lock`` while blocked on the
        engine/sink RLocks.  This phase deliberately uses only the short
        controller lock and the sink's independent failsafe path.
        """

        reason = str(reason or "cancel")
        with self._lock:
            generation = self._generation
            if expected_generation is not None and (
                generation != expected_generation
                or self._state not in ("armed", "dragging", "emergency_release")
            ):
                return {
                    "stale": True,
                    "generation": generation,
                    "releaseOk": True,
                }
            runner = self._runner
            sink = self._sink
            safety_stop = self._safety_stop
            had_resources = any(
                item is not None
                for item in (runner, sink, self._event_tap, self._safety_thread)
            )
            if had_resources:
                self._state = "emergency_release"
                self._last_cancel_reason = reason
                if safety_stop is not None:
                    safety_stop.set()
            retired_runner = self._retired_runner
            retired_sink = self._retired_sink

        target_runner = runner if runner is not None else retired_runner
        target_sink = sink if isinstance(sink, QuartzGestureSink) else retired_sink
        if isinstance(target_sink, QuartzGestureSink):
            # First close the motion admission gate.  This operation never
            # takes the sink's motion RLock.
            target_sink.request_stop(reason)
        if target_runner is not None:
            target_runner.request_stop()

        release_ok = True
        if isinstance(target_sink, QuartzGestureSink):
            try:
                release_ok = target_sink.emergency_release(reason)
            except Exception:
                release_ok = False
        return {
            "stale": False,
            "generation": generation,
            "runner": runner,
            "sink": sink,
            "hadResources": had_resources,
            "releaseOk": release_ok,
        }

    def _cancel_serial(
        self,
        reason: str = "cancel",
        expected_generation: Optional[int] = None,
        emergency: Optional[dict] = None,
    ) -> dict:
        reason = str(reason or "cancel")
        emergency = emergency or self._begin_emergency(
            reason, expected_generation=expected_generation
        )
        if emergency.get("stale"):
            with self._lock:
                state = self._state
            return {
                "cancelled": False,
                "state": state,
                "reason": "stale_watchdog_ignored",
                "releaseOk": True,
            }
        with self._lock:
            # Another cancellation may have completed while this caller was
            # waiting for the serial lock.  Never let an old token tear down a
            # newly armed generation.
            if (
                self._generation != emergency.get("generation")
                or self._runner is not emergency.get("runner")
                or self._sink is not emergency.get("sink")
            ):
                return {
                    "cancelled": False,
                    "state": self._state,
                    "reason": "cancel_already_processed",
                    "releaseOk": bool(emergency.get("releaseOk", True)),
                    "cleanupPending": self._state == "cleanup_pending",
                }
            if (
                not emergency.get("hadResources")
                and (
                    self._state == "cleanup_pending"
                    or self._retired_runner is not None
                    or self._retired_sink is not None
                )
            ):
                # The prephase may retry the retired sink's failsafe UP, but a
                # duplicate cancel must never detach the sole reaper or report
                # the quarantined generation as disarmed.
                return {
                    "cancelled": False,
                    "state": "cleanup_pending",
                    "reason": reason,
                    "releaseOk": bool(emergency.get("releaseOk", True)),
                    "cleanupPending": True,
                }
            runner = self._runner
            engine = self._engine
            sink = self._sink
            recording_sink = self._recording_sink
            interlock = self._interlock
            observer = self._observer
            feedback = self._feedback_state
            event_tap = self._event_tap
            safety_stop = self._safety_stop
            safety_thread = self._safety_thread
            session_id = self._session_id
            had_resources = bool(emergency.get("hadResources"))
            if safety_stop is not None:
                safety_stop.set()

        release_ok = bool(emergency.get("releaseOk", True))
        if runner is not None:
            try:
                runner_stopped = runner.stop(timeout=0.75, cancel=True)
            except Exception:
                runner_stopped = False
                release_ok = False
        else:
            runner_stopped = True

        close_ok = True
        if isinstance(sink, QuartzGestureSink) and runner_stopped:
            try:
                close_ok = sink.close(blocking=True)
            except Exception:
                close_ok = False
            release_ok = close_ok and release_ok
        elif isinstance(sink, QuartzGestureSink):
            # Never wait on, or release the source beneath, a timed-out native
            # post.  The reaper owns final UP and CFRelease.
            try:
                sink.close(blocking=False)
            except Exception:
                release_ok = False
        observer_status = None
        if observer is not None:
            # Mouse release deliberately happens first. A blocked observer can
            # never delay the emergency UP path or keep the sink alive.
            try:
                observer.close(reason)
            except Exception:
                pass
            try:
                observer_status = observer.status()
            except Exception:
                observer_status = {
                    "mode": "passive",
                    "closed": True,
                    "lastError": "observer_status_failed",
                }
        feedback_status = feedback.status() if feedback is not None else None
        if event_tap is not None:
            try:
                event_tap.stop()
            except Exception:
                pass
        if safety_thread is not None and safety_thread is not current_thread():
            safety_thread.join(0.10)

        cleanup_needed = bool(
            had_resources
            and (
                not runner_stopped
                or (isinstance(sink, QuartzGestureSink) and not close_ok)
            )
        )
        if had_resources and not cleanup_needed:
            final_statistics = self.statistics()
            self._trace.record({"event": "session_end", "sessionId": session_id,
                                "reason": reason, "releaseOk": release_ok,
                                "statistics": final_statistics})
            last_session = {"sessionId": session_id, "reason": reason,
                            "releaseOk": release_ok, "statistics": final_statistics,
                            "recentEvents": self._trace.recent(session_id)}
        else:
            last_session = None

        with self._lock:
            self._engine = None
            self._runner = None
            self._sink = None
            self._recording_sink = None
            self._interlock = None
            self._observer = None
            self._feedback_state = None
            if observer is not None:
                self._last_observer = observer
                if bool((observer_status or {}).get("alive")):
                    self._retired_observer = observer
                elif self._retired_observer is observer:
                    self._retired_observer = None
            if observer_status is not None:
                self._last_observer_status = observer_status
            if feedback_status is not None:
                self._last_feedback_status = feedback_status
            self._event_tap = None
            self._safety_stop = None
            self._safety_thread = None
            self._locked_pid = None
            self._locked_display_bounds = None
            self._synthetic_calibration = False
            if cleanup_needed:
                self._retired_runner = runner
                self._retired_sink = sink if isinstance(sink, QuartzGestureSink) else None
                self._state = "cleanup_pending"
                cleanup_thread = Thread(
                    target=self._reap_cancelled_session,
                    args=(
                        runner,
                        sink,
                        engine,
                        recording_sink,
                        interlock,
                        session_id,
                        reason,
                        release_ok,
                    ),
                    name="wheel-session-reaper",
                    daemon=True,
                )
                self._cleanup_thread = cleanup_thread
            else:
                self._state = "disarmed"
                self._retired_runner = None
                self._retired_sink = None
                self._cleanup_thread = None
                cleanup_thread = None
            if last_session is not None:
                self._last_session = last_session
        self._cadence.reset()
        if cleanup_thread is not None:
            cleanup_thread.start()
        if had_resources:
            self._emit_status(reason)
        with self._lock:
            result_state = self._state
        return {
            "cancelled": had_resources,
            "state": result_state,
            "reason": reason,
            "releaseOk": release_ok,
            "cleanupPending": cleanup_needed,
        }

    def _reap_cancelled_session(
        self,
        runner: Optional[GestureRunner],
        sink,
        engine: Optional[GestureEngine],
        recording_sink: Optional[_ObservedRecordingSink],
        interlock: Optional[InputInterlock],
        session_id: Optional[str],
        reason: str,
        initial_release_ok: bool,
    ) -> None:
        """Finish cleanup after a timed-out native post, off the caller path."""

        if runner is not None:
            runner.join(None)

        final_release_ok = initial_release_ok
        if isinstance(sink, QuartzGestureSink):
            # A persistent UP failure remains quarantined.  Retrying here is
            # preferable to releasing the only recovery source or reporting a
            # false disarmed state.
            while True:
                try:
                    final_up = sink.emergency_release("runner_exit_final")
                    close_ok = sink.close(blocking=True) if final_up else False
                except Exception:
                    final_up = False
                    close_ok = False
                if final_up and close_ok:
                    final_release_ok = True
                    break
                final_release_ok = False
                time.sleep(0.05)

        final_statistics = self._statistics_for(
            engine, recording_sink, interlock
        )
        self._trace.record(
            {
                "event": "session_end",
                "sessionId": session_id,
                "reason": reason,
                "releaseOk": final_release_ok,
                "statistics": final_statistics,
            }
        )
        last_session = {
            "sessionId": session_id,
            "reason": reason,
            "releaseOk": final_release_ok,
            "statistics": final_statistics,
            "recentEvents": self._trace.recent(session_id),
        }
        with self._lock:
            if self._retired_runner is runner and self._retired_sink is (
                sink if isinstance(sink, QuartzGestureSink) else None
            ):
                self._retired_runner = None
                self._retired_sink = None
                self._cleanup_thread = None
                self._state = "disarmed"
                self._last_session = last_session
        self._emit_status("cleanup_complete")

    def shutdown(self, reason: str = "shutdown") -> dict:
        with self._lock:
            already = self._shutdown
            if already:
                return {
                    "cancelled": False,
                    "state": self._state,
                    "reason": "already_shutdown",
                    "releaseOk": True,
                    "alreadyShutdown": True,
                }
            self._shutdown = True
        result = self.cancel(reason)
        self._trace.close()
        result["alreadyShutdown"] = already
        return result

    def status(self, include_preflight: bool = False) -> dict:
        with self._lock:
            observer = self._observer
            last_observer = self._last_observer
            last_observer_status = self._last_observer_status
            feedback = self._feedback_state
            last_feedback_status = self._last_feedback_status
            sink = self._sink
            result = {
                "state": self._state,
                "armed": self._state in ("armed", "dragging"),
                "outputMode": self._config.output_mode,
                "config": self._config.as_dict(),
                "calibration": self._calibration.as_dict(),
                "lockedPid": self._locked_pid,
                "lastCancelReason": self._last_cancel_reason,
                "windowsIdleRecalibrationRequired": self._windows_idle_recalibration is not None,
                "windowsIdleRecalibration": (
                    dict(self._windows_idle_recalibration)
                    if self._windows_idle_recalibration is not None else None
                ),
                "syntheticCalibration": self._synthetic_calibration,
                "runtimeVersion": RUNTIME_VERSION,
                "pointerStrategy": (
                    "fixed_10x_hid_session_with_timed_tourbox_rebase"
                ),
                "pointerTuning": {
                    "active": isinstance(sink, QuartzGestureSink),
                    "locationScale": LIVE_LOCATION_SCALE,
                    "requestedLocationScale": LIVE_LOCATION_SCALE,
                    "effectiveLocationScale": LIVE_LOCATION_SCALE,
                    "deltaScale": LOGICAL_DELTA_SCALE,
                    "anchor": "piecewise_mapping_rebased_while_down",
                    "relativeDeltaSpace": "zeroed_event_fields",
                    "quantizedDeltaTracksLocation": False,
                    "detachCursor": True,
                    "targetedPost": False,
                    "eventPostRoute": "hid_session_tap",
                    "rebaseWhileDown": True,
                    "rebaseTarget": "safe_display_center",
                    "rebaseTransport": (
                        "timed_sentinel_then_cursor_warp_then_duplicate_anchor"
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
                    "edgeMargin": LIVE_EDGE_MARGIN,
                },
                "sessionId": self._session_id,
                "gestureTiming": dict(self._gesture_timing),
                "lastSession": self._last_session,
                "autoRecognition": (
                    dict(self._last_auto_recognition)
                    if self._last_auto_recognition is not None
                    else None
                ),
            }
        if isinstance(sink, QuartzGestureSink):
            scale_status = sink.location_scale_status()
            result["pointerTuning"]["locationScale"] = scale_status["effective"]
            result["pointerTuning"]["effectiveLocationScale"] = (
                scale_status["effective"]
            )
            result["pointerTuning"]["locationScaleSafety"] = scale_status
        else:
            result["pointerTuning"]["locationScaleSafety"] = {
                "enabled": False,
                "resolved": False,
                "requested": LIVE_LOCATION_SCALE,
                "effective": LIVE_LOCATION_SCALE,
                "attenuated": False,
                "strategy": "inactive_recording_or_disarmed",
                "edgeMargin": LIVE_EDGE_MARGIN,
                "postEdgeMargin": 2.0,
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
                "rebaseCount": 0,
                "burstRebaseCount": 0,
                "rebasePending": False,
                "rebasePhase": None,
                "rebaseNextDeadline": None,
                "anchor": None,
                "displayBounds": None,
                "safeBounds": None,
                "rebaseBounds": None,
                "wheelBounds": None,
                "mappingLogicalAnchor": None,
                "mappingEventAnchor": None,
            }
        if getattr(self._bindings, "platform_name", None) == "Windows":
            tuning = result["pointerTuning"]
            scale_status = tuning["locationScaleSafety"]
            if not isinstance(sink, WindowsGestureSink):
                scale_status.update(
                    requested=WINDOWS_LOCATION_SCALE, effective=WINDOWS_LOCATION_SCALE,
                    edgeMargin=WINDOWS_EDGE_MARGIN,
                    rebaseWhileDown=False, rebaseTransport="win32_verified_origin_continue",
                    outOfBoundsDragEvents=False, outOfBoundsDragScope=None,
                )
            result["pointerStrategy"] = "fixed_10x_win32_with_verified_origin"
            tuning.update(
                locationScale=scale_status["effective"],
                requestedLocationScale=scale_status["requested"],
                effectiveLocationScale=scale_status["effective"],
                anchor="piecewise_mapping_with_verified_native_origin",
                relativeDeltaSpace="physical_desktop_pixels",
                detachCursor=False,
                eventPostRoute="win32_sendinput",
                rebaseWhileDown=scale_status["rebaseWhileDown"],
                rebaseTarget=scale_status["rebaseTarget"],
                rebaseTransport=scale_status["rebaseTransport"],
                outOfBoundsDragEvents=False,
                outOfBoundsDragScope=None,
                hostReanchorSemantics="preserve_model_and_pending_motion",
                restoreAfterIdleUp=False,
                edgeMargin=scale_status["edgeMargin"],
            )
            # These delays belong only to the macOS sentinel/warp protocol.
            for key in ("rebaseWarpDelayMs", "rebaseAnchorDelayMs",
                        "rebaseMinAnchorAfterWarpMs", "rebaseMotionAfterAnchorMs"):
                tuning.pop(key, None)
                scale_status.pop(key, None)
        if observer is not None:
            try:
                result["observer"] = observer.status()
            except Exception:
                result["observer"] = {
                    "mode": "passive",
                    "started": True,
                    "lastError": "observer_status_failed",
                    "observerOnly": False,
                }
        elif last_observer is not None:
            try:
                result["observer"] = last_observer.status()
            except Exception:
                result["observer"] = dict(last_observer_status or {
                    "mode": "passive",
                    "observerOnly": False,
                    "started": True,
                    "closed": True,
                    "alive": False,
                    "lastError": "observer_status_failed",
                })
        elif last_observer_status is not None:
            result["observer"] = dict(last_observer_status)
        else:
            result["observer"] = {
                "mode": "passive",
                "started": False,
                "closed": True,
                "alive": False,
                "observerOnly": False,
            }
        if feedback is not None:
            result["wheelFeedback"] = feedback.status()
        elif last_feedback_status is not None:
            result["wheelFeedback"] = dict(last_feedback_status)
        else:
            result["wheelFeedback"] = {
                "active": False,
                "needsFreshHandle": True,
                "lastReason": "not_armed",
            }
        result["statistics"] = self.statistics()
        result["diagnostics"] = self._trace.statistics()
        if include_preflight:
            result["preflight"] = self.preflight()
        return result

    def statistics(self) -> dict:
        with self._lock:
            engine = self._engine
            recording_sink = self._recording_sink
            interlock = self._interlock
        return self._statistics_for(engine, recording_sink, interlock)

    @staticmethod
    def _statistics_for(
        engine: Optional[GestureEngine],
        recording_sink: Optional[_ObservedRecordingSink],
        interlock: Optional[InputInterlock],
    ) -> dict:
        result: Dict[str, object] = {
            "submittedAngle": 0.0,
            "submittedRadial": 0.0,
            "consumedAngle": 0.0,
            "consumedRadial": 0.0,
            "pendingAngle": 0.0,
            "pendingRadial": 0.0,
            "sessionActive": False,
            "transportPending": False,
            "modelOutputReady": False,
            "engineCancelled": False,
        }
        if engine is not None:
            snapshot = engine.snapshot()
            result.update(
                {
                    "submittedAngle": snapshot.submitted_angle,
                    "submittedRadial": snapshot.submitted_radial,
                    "consumedAngle": snapshot.consumed_angle,
                    "consumedRadial": snapshot.consumed_radial,
                    "pendingAngle": snapshot.pending_angle,
                    "pendingRadial": snapshot.pending_radial,
                    "sessionActive": snapshot.session_active,
                    "transportPending": snapshot.transport_pending,
                    "modelOutputReady": getattr(snapshot, "output_ready", True),
                    "engineCancelled": getattr(snapshot, "cancelled", False),
                    "freshHandleBarrier": snapshot.fresh_handle_required,
                    "freshHandleEpoch": snapshot.fresh_handle_epoch,
                    "modelHandle": _vec_dict(snapshot.handle),
                    "modelRadius": snapshot.radius,
                    "effectiveMaxRadius": snapshot.effective_max_radius,
                    "lastNonzeroAxis": _vec_dict(snapshot.last_nonzero_axis),
                    "diameterAxis": _vec_dict(snapshot.diameter_axis),
                    "signedRadius": snapshot.signed_radius,
                    "diameterLastSide": snapshot.diameter_last_side,
                    "motionRevision": snapshot.motion_revision,
                    "modelRevision": snapshot.model_revision,
                    "alignmentPending": snapshot.alignment_pending,
                    "alignmentActive": snapshot.alignment_active,
                    "alignmentRemainingPx": snapshot.alignment_remaining,
                }
            )
        if recording_sink is not None:
            counts = {kind.value: 0 for kind in PointerEventKind}
            for event in recording_sink.events:
                counts[event.kind.value] += 1
            result["recordedEvents"] = counts
            result["recordedEventTotal"] = sum(counts.values())
        if interlock is not None:
            result["interlock"] = interlock.statistics()
        return result

    def _on_pointer_state(self, down: bool) -> None:
        with self._lock:
            if self._state not in ("armed", "dragging"):
                return
            self._state = "dragging" if down else "armed"

    def _safety_loop(self, stop: Event, generation: int) -> None:
        last_environment_check = 0.0
        while not stop.wait(0.02):
            now = self._clock()
            with self._lock:
                interlock = self._interlock
                tap = self._event_tap
                runner = self._runner
                sink = self._sink
                locked_pid = self._locked_pid
                locked_display_bounds = self._locked_display_bounds
                calibration_handle = self._calibration.handle
                state = self._state
            if state not in ("armed", "dragging"):
                return
            if interlock is None or tap is None or runner is None:
                self._cancel_generation("safety_components_missing", generation)
                return
            if (
                isinstance(sink, QuartzGestureSink)
                and sink.owns_down
                and now - runner.heartbeat_at > 0.35
            ):
                self._cancel_generation("pointer_session_watchdog", generation)
                return
            reason = interlock.watchdog_reason(now)
            if reason:
                self._cancel_generation(reason, generation)
                return
            if not tap.alive:
                self._cancel_generation(tap.error or "event_tap_stopped", generation)
                return
            if not runner.running:
                self._cancel_generation("gesture_runner_stopped", generation)
                return
            if now - last_environment_check < 0.05:
                continue
            last_environment_check = now
            try:
                permissions = self._bindings.permissions()
                app = self._bindings.frontmost_app()
            except Exception:
                self._cancel_generation("environment_check_failed", generation)
                return
            if not permissions.ready:
                self._cancel_generation("permission_lost", generation)
                return
            if not app.is_davinci:
                self._cancel_generation("focus_lost", generation)
                return
            if app.pid != locked_pid:
                self._cancel_generation("davinci_pid_changed", generation)
                return
            display_resolver = getattr(
                self._bindings, "display_bounds_for_point", None
            )
            if (
                not callable(display_resolver)
                or calibration_handle is None
                or locked_display_bounds is None
            ):
                self._cancel_generation("display_bounds_changed", generation)
                return
            try:
                current_display_bounds = tuple(
                    float(value)
                    for value in display_resolver(
                        (calibration_handle.x, calibration_handle.y)
                    )
                )
            except Exception:
                self._cancel_generation("display_bounds_changed", generation)
                return
            if current_display_bounds != tuple(locked_display_bounds):
                self._cancel_generation("display_bounds_changed", generation)
                return
            try:
                external_down = interlock.unowned_button_down(
                    self._bindings.left_button_down
                )
            except Exception:
                self._cancel_generation("environment_check_failed", generation)
                return
            if external_down:
                self._cancel_generation("external_left_button_down", generation)
                return

    @staticmethod
    def _engine_config(
        profile: str,
        double_click_interval: float = 0.5,
        *,
        live: bool = False,
    ) -> GestureConfig:
        # The measured TourBox lifecycle releases about 500 ms after input.
        # Keep the platform double-click guard authoritative when it is longer;
        # recording retains its established 650 ms deterministic behavior.
        guard = double_click_interval + 0.05
        # Ordinary orbit retains its established 0.75 degree cadence. Only
        # explicitly identified flick input can use a bounded 3-degree slice.
        # Split one measured 1 px TourBox radial callback across two 120 Hz
        # frames: this preserves
        # throughput while avoiding a 10 px synthetic-pointer jump per frame.
        angle_limit, radial_limit = (0.75, 0.50)
        idle_floor = 0.500 if live else 0.650
        return GestureConfig(idle_timeout=max(idle_floor, guard), min_down_interval=guard,
                             continuous_orbit=live and profile == "tourbox_like",
                             orbit_pacing_window=.045 if live and profile == "tourbox_like" else 0.0,
                             orbit_pacing_max_window=.075 if live and profile == "tourbox_like" else 0.0,
                             max_angle_per_frame=angle_limit, max_radial_per_frame=radial_limit,
                             axis_alignment_step=0.5 if profile == "tourbox_like" else 0.0,
                             orbit_alignment_step=1.0 if profile == "tourbox_like" else 0.0,
                             max_flick_angle_per_frame=3.0 if profile == "tourbox_like" else 0.0,
                             flick_accel_per_frame=0.75 if profile == "tourbox_like" else 0.0,
                             max_flick_radial_per_frame=1.5 if profile == "tourbox_like" else 0.0,
                             radial_accel_per_frame=0.5 if profile == "tourbox_like" else 0.0)

    def _record_pointer(self, event: dict) -> None:
        # Called under engine/sink locks: only enqueue, never acquire _lock or
        # write a pipe/file here. Session changes are cancel-lock serialized.
        if (self._config.output_mode == "live" and event.get("kind") == "down"
                and event.get("ok", True)):
            self._last_mouse_down_at = event.get("monotonic", self._clock())
        self._trace.record({"event": "pointer", "sessionId": self._session_id,
                            "outputMode": self._config.output_mode, **event})
        feedback = self._feedback_state
        if feedback is not None:
            try:
                feedback.note_pointer(event)
            except Exception:
                # Feedback state is observational on the hot path. A malformed
                # trace can never interrupt an owned pointer lifecycle.
                pass
        observer = self._observer
        if observer is not None:
            try:
                observer.note_pointer(event)
            except Exception:
                # This path runs under sink/engine locks. Scheduling is
                # best-effort and cannot affect the pointer lifecycle.
                pass

    def _retire_windows_idle_feedback(self, engine, feedback, generation,
                                      observed_revision, expected, reason):
        """Invalidate an idle prediction without adopting one suspect sample.

        Windows deliberately has no in-motion fresh-observer loop. Retiring the
        generation makes the next input obtain a separate fresh calibration.
        Match input's engine -> controller lock order; never join a worker while
        holding the engine lock.
        """
        with engine._lock:
            snapshot = engine.snapshot()
            if (snapshot.session_active or snapshot.transport_pending
                    or snapshot.alignment_pending or snapshot.alignment_active
                    or abs(snapshot.pending_angle) + abs(snapshot.pending_radial) > 1e-9
                    or snapshot.motion_revision != observed_revision
                    or (snapshot.handle - expected).length > 1e-9):
                return False
            with self._lock:
                if (self._generation != generation or self._engine is not engine
                        or self._feedback_state is not feedback
                        or self._state not in ("armed", "dragging")):
                    return False
                self._windows_idle_recalibration = {
                    "generation": generation, "motionRevision": observed_revision,
                    "reason": str(reason), "requestedAt": self._clock(),
                }
                # Publish distrust before releasing the admission lock. This
                # also prevents the backend committing the rejected prediction
                # while bounded cleanup is still completing.
                self._state = "emergency_release"
                self._last_cancel_reason = WINDOWS_IDLE_RECALIBRATION_REASON
                runner, sink = self._runner, self._sink
                if self._safety_stop is not None:
                    self._safety_stop.set()
            if isinstance(sink, QuartzGestureSink):
                sink.request_stop(WINDOWS_IDLE_RECALIBRATION_REASON)
            if runner is not None:
                runner.request_stop()
        self._cancel_generation(WINDOWS_IDLE_RECALIBRATION_REASON, generation)
        return True

    def _apply_visual_feedback(
        self,
        result: dict,
        *,
        engine: GestureEngine,
        feedback: WheelFeedbackState,
        generation: int,
        session_id: Optional[str],
    ) -> None:
        """Plan and atomically apply one latest visual checkpoint."""

        # Observation and feedback may race with input. Label both snapshots
        # explicitly; these fields are evidence, not a new source of control.
        trace_context = {
            "observationRevision": result.get("revision"),
            "gestureId": result.get("gestureId"),
            "trigger": result.get("trigger"),
            "observedMode": result.get("mode"),
            "actual": result.get("actual"),
            "observedPredicted": result.get("predicted"),
            "observedMotionRevision": result.get("motionRevision"),
            "observedFreshHandleEpoch": result.get("freshHandleEpoch", 0),
            "observationTiming": result.get("timing"),
        }
        with self._lock:
            current = (
                self._generation == generation
                and self._engine is engine
                and self._feedback_state is feedback
                and self._state in ("armed", "dragging")
            )
            observer = self._observer if current else None
        if not current or result.get("generation") != generation:
            self._trace.record(
                {
                    **trace_context,
                    "event": "wheel_feedback",
                    "sessionId": session_id,
                    "generation": generation,
                    "result": "discarded",
                    "reason": "stale_generation",
                }
            )
            return

        observed_motion_revision = result.get("motionRevision")
        if (
            isinstance(observed_motion_revision, bool)
            or not isinstance(observed_motion_revision, int)
            or observed_motion_revision < 0
        ):
            self._trace.record(
                {
                    **trace_context,
                    "event": "wheel_feedback",
                    "sessionId": session_id,
                    "generation": generation,
                    "result": "discarded",
                    "reason": "invalid_motion_revision",
                }
            )
            return

        snapshot = engine.snapshot()
        idle_only = getattr(getattr(self, "_bindings", None), "platform_name", None) == "Windows"
        if idle_only and (snapshot.session_active or
                          abs(snapshot.pending_angle) + abs(snapshot.pending_radial) > 1e-9):
            return
        if snapshot.alignment_active or (snapshot.alignment_pending and snapshot.alignment_mode == "orbit"):
            self._trace.record({**trace_context, "event": "wheel_feedback",
                                "sessionId": session_id, "generation": generation,
                                "result": "discarded", "reason": "axis_alignment_active"})
            return
        trace_context["modelBeforeFeedback"] = {
            "handle": _vec_dict(snapshot.handle),
            "diameterAxis": _vec_dict(getattr(snapshot, "diameter_axis", None)),
            "signedRadius": getattr(snapshot, "signed_radius", None),
            "lastNonzeroAxis": _vec_dict(getattr(snapshot, "last_nonzero_axis", None)),
            "diameterLastSide": getattr(snapshot, "diameter_last_side", None),
            "modelRevision": getattr(snapshot, "model_revision", None),
            "motionRevision": snapshot.motion_revision,
            "freshHandleEpoch": snapshot.fresh_handle_epoch,
            "freshHandleRequired": snapshot.fresh_handle_required,
            "pendingAngle": snapshot.pending_angle,
            "pendingRadial": snapshot.pending_radial,
            "sessionActive": snapshot.session_active,
            "activeMode": getattr(snapshot.active_mode, "value", snapshot.active_mode),
        }
        observed_fresh_epoch = result.get("freshHandleEpoch", 0)
        if (
            isinstance(observed_fresh_epoch, bool)
            or not isinstance(observed_fresh_epoch, int)
            or observed_fresh_epoch < 0
        ):
            self._trace.record(
                {
                    **trace_context,
                    "event": "wheel_feedback",
                    "sessionId": session_id,
                    "generation": generation,
                    "result": "discarded",
                    "reason": "invalid_fresh_handle_epoch",
                }
            )
            return
        if (
            snapshot.fresh_handle_required
            and observed_fresh_epoch != snapshot.fresh_handle_epoch
        ):
            self._trace.record(
                {
                    **trace_context,
                    "event": "wheel_feedback",
                    "sessionId": session_id,
                    "generation": generation,
                    "result": "discarded",
                    "reason": "stale_fresh_handle_epoch",
                    "observedFreshHandleEpoch": observed_fresh_epoch,
                    "currentFreshHandleEpoch": snapshot.fresh_handle_epoch,
                }
            )
            return
        # While a fresh barrier is active, later encoder callbacks only append
        # to the paused queue. They advance motionRevision without changing the
        # model point, so the barrier epoch is the authoritative capture CAS.
        protected_prebarrier_probe = bool(
            not snapshot.fresh_handle_required
            and result.get("trigger") == "fresh_recovery"
            and feedback.status().get("hardFreshRequired")
        )
        stale_input_revision = snapshot.motion_revision != observed_motion_revision
        orbit_probe_only = bool(
            stale_input_revision
            and not snapshot.fresh_handle_required
            and not protected_prebarrier_probe
            and snapshot.active_mode == GestureMode.ORBIT
            and observed_fresh_epoch == snapshot.fresh_handle_epoch
            and feedback.can_probe_orbit_motion(result, snapshot.handle, self._clock())
        )
        if (stale_input_revision and not snapshot.fresh_handle_required
                and not protected_prebarrier_probe and not orbit_probe_only):
            self._trace.record(
                {
                    **trace_context,
                    "event": "wheel_feedback",
                    "sessionId": session_id,
                    "generation": generation,
                    "result": "discarded",
                    "reason": "stale_motion_revision",
                    "observedMotionRevision": observed_motion_revision,
                    "currentMotionRevision": snapshot.motion_revision,
                }
            )
            return
        pending_motion = abs(snapshot.pending_angle) + abs(snapshot.pending_radial)
        decision = feedback.consider(
            result,
            current_handle=snapshot.handle,
            session_active=snapshot.session_active,
            pending_motion=pending_motion,
            fresh_barrier=snapshot.fresh_handle_required,
            diameter_axis=(
                snapshot.diameter_axis
                if snapshot.active_mode == GestureMode.PUSH_PULL
                else None
            ),
            motion_is_current=not stale_input_revision or orbit_probe_only,
            orbit_probe_only=orbit_probe_only,
        )
        idle_recalibration_retired = False
        if idle_only and decision.get("requireFreshBarrier"):
            idle_recalibration_retired = self._retire_windows_idle_feedback(
                engine, feedback, generation, observed_motion_revision,
                snapshot.handle, decision.get("reason") or "visual_feedback",
            )
        if (decision.get("requestOrbitConfirmation") and observer is not None
                and not idle_only):
            # More independent samples are required before authorizing any
            # correction. This schedules capture only; pointer output continues.
            try:
                observer.request_fresh_recovery("orbit", force_next=True)
            except Exception:
                pass
        barrier_applied = False
        barrier_epoch = None
        recovery_requested = False
        if decision.get("requireFreshBarrier") and not idle_only:
            with self._lock:
                still_current = (
                    self._generation == generation
                    and self._engine is engine
                    and self._feedback_state is feedback
                    and self._state in ("armed", "dragging")
                )
            if still_current:
                barrier_epoch = engine.require_fresh_handle(
                    reason=str(decision.get("reason") or "visual_feedback")
                )
                barrier_applied = barrier_epoch > 0
        if barrier_applied and observer is not None:
            try:
                active_mode = getattr(snapshot.active_mode, "value", snapshot.active_mode)
                recovery_requested = observer.request_fresh_recovery(
                    active_mode or result.get("mode") or "unknown",
                    force_next=(
                        observed_fresh_epoch != barrier_epoch
                        or result.get("trigger") == "fresh_recovery"
                    ),
                )
            except Exception:
                # The barrier remains fail-closed. A terminal or later quiet
                # sample can still recover it if this prompt request fails.
                recovery_requested = False
        applied = False
        adopted_point = None
        committed = False
        released_barrier = False
        if decision.get("applyCorrection") and not idle_recalibration_retired:
            correction = decision.get("correction") or decision.get("actual") or {}
            expected = decision.get("expected") or {}
            correction_point = Vec2(
                float(correction["x"]), float(correction["y"])
            )
            expected_point = Vec2(float(expected["x"]), float(expected["y"]))
            with self._lock:
                still_current = (
                    self._generation == generation
                    and self._engine is engine
                    and self._feedback_state is feedback
                    and self._state in ("armed", "dragging")
                )
            if still_current:
                adopted_point = engine.reconcile_idle_handle(
                    correction_point,
                    expected_point,
                    preserve_diameter_axis=bool(
                        decision.get("preserveDiameterAxis")
                    ),
                    restore_orbit_path=bool(decision.get("restoreOrbitPath")),
                    effective_max_radius=decision.get("learnedMaxRadius"),
                    tolerance=max(1.5, feedback.visual_max_radius * 0.04),
                    expected_motion_revision=observed_motion_revision,
                    expected_fresh_epoch=(
                        observed_fresh_epoch
                        if snapshot.fresh_handle_required
                        else None
                    ),
                )
            committed = feedback.complete_correction(
                adopted_point or correction_point,
                applied=adopted_point is not None,
                token=decision["correctionToken"],
                learned_max_radius=decision.get("learnedMaxRadius"),
            )
            applied = bool(adopted_point is not None and committed)
            if applied and snapshot.fresh_handle_required:
                released_barrier = engine.release_fresh_handle(
                    snapshot.fresh_handle_epoch,
                    adopted_point,
                )
                applied = bool(released_barrier)
                if not released_barrier:
                    feedback.mark_fresh_required("fresh_barrier_release_failed")
        self._trace.record(
            {
                **trace_context,
                "event": "wheel_feedback",
                "sessionId": session_id,
                "generation": generation,
                "result": "applied" if applied else "observed",
                "freshBarrierApplied": barrier_applied,
                "freshBarrierEpoch": barrier_epoch,
                "freshRecoveryRequested": recovery_requested,
                "freshBarrierReleased": released_barrier,
                "protectedPrebarrierProbe": protected_prebarrier_probe,
                "orbitProbeOnly": orbit_probe_only,
                "idleRecalibrationRetired": idle_recalibration_retired,
                "idleRecalibrationReason": (
                    WINDOWS_IDLE_RECALIBRATION_REASON
                    if idle_recalibration_retired else None
                ),
                "idleRecalibrationNextStep": (
                    "fresh_recognition_before_next_input"
                    if idle_recalibration_retired else None
                ),
                # This is the reconcile return, not a later snapshot: preserve
                # actual vs projected/model position, including CAS failures.
                "adoptedPoint": _vec_dict(adopted_point),
                "modelReconciled": adopted_point is not None,
                "correctionCommitted": bool(committed),
                "decision": decision,
                "state": feedback.status(),
            }
        )

    def _passive_observer_supported(self) -> bool:
        if not all(
            callable(getattr(self._bindings, name, None))
            for name in ("screen_capture_allowed", "capture_screen_region")
        ):
            return False
        probe = getattr(self._bindings, "screen_capture_supported", None)
        if not callable(probe):
            return True
        try:
            return bool(probe())
        except Exception:
            return False

    def _auto_recognition_supported(self) -> bool:
        """Require positive support for the one-shot Arm-time detector."""

        if not all(
            callable(getattr(self._bindings, name, None))
            for name in (
                "frontmost_app",
                "current_mouse_position",
                "display_bounds_for_point",
                "screen_capture_supported",
                "screen_capture_allowed",
                "capture_screen_region",
                "warp_mouse_cursor",
            )
        ):
            return False
        try:
            return bool(self._bindings.screen_capture_supported())
        except Exception:
            return False

    def _emit_status(self, reason: str) -> None:
        self._trace.record({"event": "status", "sessionId": self._session_id,
                            "reason": reason, "gestureTiming": dict(self._gesture_timing)})
        try:
            self._emit_event(
                {
                    "type": "status",
                    "reason": reason,
                    "status": self.status(include_preflight=False),
                }
            )
        except Exception:
            pass


def _positive_number(value: object, name: str, maximum: float) -> float:
    if isinstance(value, bool):
        raise WorkerError("invalid_config", "%s must be a number" % name)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise WorkerError("invalid_config", "%s must be a number" % name)
    if not math.isfinite(parsed) or parsed <= 0.0 or parsed > maximum:
        raise WorkerError(
            "invalid_config",
            "%s must be finite, greater than zero, and at most %s" % (name, maximum),
        )
    return parsed


def _vec_dict(value: Optional[Vec2]) -> Optional[dict]:
    if value is None:
        return None
    return {"x": value.x, "y": value.y}
