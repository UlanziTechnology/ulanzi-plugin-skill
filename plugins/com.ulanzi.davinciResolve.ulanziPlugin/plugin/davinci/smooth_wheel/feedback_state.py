"""Pure decision state for asynchronous wheel-handle visual feedback.

The screenshot worker owns capture and detection.  This module only validates
the small result dictionaries and decides whether a result is suitable for a
future model correction or for learning a conservative effective outer limit.
It deliberately performs no I/O and never runs on the 120 Hz motion path.
"""

from __future__ import annotations

import math
from threading import RLock
from typing import Any, Mapping, Optional

from ..config import (
    WHEEL_DIAMETER_CENTER_FEEDBACK_IGNORE_RADIUS,
    WHEEL_DIAMETER_CENTER_STATE_RADIUS,
)
from .geometry import Vec2
from .orbit_recovery import OrbitDriftGuard


MIN_CONFIRMATION_CONFIDENCE = 0.42
MAX_OUTER_LEARN_INSET_RATIO = 0.35
MAX_CORRECTION_DRIFT_RATIO = 0.35
MAX_OUTER_ALIGNMENT_DEGREES = 5.0
MAX_CROSSING_ALIGNMENT_DEGREES = 12.0
HOST_STALL_MIN_CONFIDENCE = 0.65
HOST_STALL_MIN_EXPECTED_MOTION_RATIO = 0.08
HOST_STALL_MAX_ACTUAL_MOTION_RATIO = 0.03
HOST_STALL_MIN_DRIFT_RATIO = 0.10
PUSH_PULL_STALL_MIN_EXPECTED_MOTION_RATIO = 0.06
PUSH_PULL_STALL_MIN_DRIFT_RATIO = 0.05
HOST_STALL_OBSERVATIONS = 2
# Keep the pure feedback decision and formal rearm adapter on one validated
# centre-noise boundary.  The comparison is deliberately strict.
CENTER_FEEDBACK_IGNORE_RADIUS = WHEEL_DIAMETER_CENTER_FEEDBACK_IGNORE_RADIUS


def _point(value: Any) -> Optional[Vec2]:
    if isinstance(value, Mapping):
        raw_x, raw_y = value.get("x"), value.get("y")
    elif hasattr(value, "x") and hasattr(value, "y"):
        raw_x, raw_y = value.x, value.y
    else:
        try:
            raw_x, raw_y = value
        except (TypeError, ValueError):
            return None
    try:
        point = Vec2(float(raw_x), float(raw_y))
    except (TypeError, ValueError):
        return None
    return point if math.isfinite(point.x) and math.isfinite(point.y) else None


class WheelFeedbackState:
    """Track predicted, confirmed, and freshness state for one armed wheel."""

    def __init__(
        self,
        center: Vec2,
        initial_handle: Vec2,
        visual_max_radius: float,
        *,
        preserve_initial_diameter_axis: bool = False,
        orbit_path_recovery: bool = False,
    ) -> None:
        radius = float(visual_max_radius)
        if not math.isfinite(radius) or radius <= 0.0:
            raise ValueError("visual_max_radius must be finite and positive")
        self.center = center
        self.visual_max_radius = radius
        self.predicted = initial_handle
        self.confirmed = initial_handle
        self.effective_max_radius = radius
        self.needs_fresh_handle = True
        self.center_crossing_pending = False
        self.outer_probe_pending = False
        self.last_reason = "arm_requires_baseline"
        self.last_drift_px = 0.0
        self.confirmations = 0
        self.rejections = 0
        self.corrections = 0
        self.outer_limit_learns = 0
        self.host_stall_pending = False
        self.no_progress_observations = 0
        self._hard_fresh_required = False
        self._center_continuation_blocked = False
        self.center_continuations = 0
        self._host_stall_anchor: Optional[Vec2] = None
        self._host_stall_gesture_id: Optional[int] = None
        self._host_stall_mode = ""
        self._stationary_anchor_actual: Optional[Vec2] = None
        self._stationary_anchor_expected: Optional[Vec2] = None
        self._stationary_gesture_id: Optional[int] = None
        self._stationary_mode = ""
        self._last_observation_actual: Optional[Vec2] = None
        self._last_observation_expected: Optional[Vec2] = None
        self._last_pointer_mode = ""
        self._push_pull_axis_observed = False
        # A restored formal diameter is already authoritative before the first
        # pointer frame. A fresh unseeded observation must still be free to
        # establish its initial axis. This flag stores trust, never an old axis:
        # reconciliation always projects onto the engine's current model axis.
        self._preserve_initial_diameter_axis = bool(preserve_initial_diameter_axis)
        self._revision = 0
        self._orbit_drift = OrbitDriftGuard(center, radius) if orbit_path_recovery else None
        self._lock = RLock()

    def note_pointer(self, event: Any) -> None:
        """Consume a lightweight sink trace without blocking its caller."""

        if not isinstance(event, Mapping) or event.get("ok") is False:
            return
        with self._lock:
            # Every owned pointer event starts a newer input epoch.  Visual
            # correction plans carry this revision as a compare-and-swap
            # token so an old screenshot cannot commit over a new gesture.
            self._revision += 1
            logical = event.get("logical")
            if isinstance(logical, Mapping):
                mode = str(logical.get("mode") or "")
                if mode:
                    self._last_pointer_mode = mode
                before = _point(logical.get("before"))
                after = _point(logical.get("after"))
                if after is not None:
                    self.predicted = after
                if (
                    mode == "push_pull"
                    and before is not None
                    and after is not None
                    and (after - before).length > 1e-9
                ):
                    self._push_pull_axis_observed = True
                if bool(logical.get("crossedCenter")):
                    self.needs_fresh_handle = True
                    self.center_crossing_pending = True
                    self._hard_fresh_required = True
                    self.last_reason = "center_crossing_requires_confirmation"
                if bool(logical.get("clamped")):
                    self.needs_fresh_handle = True
                    self.outer_probe_pending = True
                    self._hard_fresh_required = True
                    self._center_continuation_blocked = True
                    self.last_reason = "outer_clamp_requires_confirmation"
            kind = str(event.get("kind") or "")
            if "rebase" in kind:
                self.needs_fresh_handle = True
                if self.center_crossing_pending:
                    self._center_continuation_blocked = True
                self.last_reason = "pointer_rebase_requires_confirmation"

    def can_probe_orbit_motion(self, observation, current_handle, now):
        with self._lock:
            return bool(self._orbit_drift and self._orbit_drift.recent_probe(
                observation, _point(observation.get("predicted")), current_handle, now,
            ))

    def consider(
        self,
        observation: Any,
        *,
        current_handle: Vec2,
        session_active: bool,
        pending_motion: float,
        fresh_barrier: bool = False,
        diameter_axis: Optional[Vec2] = None,
        motion_is_current: bool = False,
        orbit_probe_only: bool = False,
    ) -> dict:
        """Validate one latest-only observation and return a correction plan.

        A visual result can update ``confirmed`` while a pointer is down, but a
        model correction is only authorized after the gesture has ended and the
        lossless input queue is empty.  The caller remains responsible for a
        generation check immediately before applying the returned point.
        """

        with self._lock:
            actual = (
                _point(observation.get("actual"))
                if isinstance(observation, Mapping)
                else None
            )
            expected = (
                _point(observation.get("predicted"))
                if isinstance(observation, Mapping)
                else None
            )
            confidence = self._confidence(observation)
            trigger = (
                str(observation.get("trigger") or "")
                if isinstance(observation, Mapping)
                else ""
            )
            mode = (
                str(observation.get("mode") or self._last_pointer_mode)
                if isinstance(observation, Mapping)
                else self._last_pointer_mode
            )
            if trigger in ("fresh_recovery", "arm_baseline") and self._last_pointer_mode:
                # A baseline scheduled at arm can finish after the first input.
                # Follow the consumed mode: a push/pull has established its axis,
                # whereas an intervening orbit is allowed to change that axis.
                mode = self._last_pointer_mode
            gesture_id = self._gesture_id(observation)
            orbit_recovery = bool(self._orbit_drift and self._orbit_drift.sample(
                observation, actual, expected, current_handle, mode,
                current_motion=motion_is_current,
                fresh_stationary=(fresh_barrier and not session_active
                                  and trigger == "fresh_recovery"),
            ))
            orbit_candidate = bool(self._orbit_drift and self._orbit_drift.count)
            if self._orbit_drift and self._orbit_drift.pending:
                self._hard_fresh_required = True
                self.needs_fresh_handle = True
                if not orbit_recovery:
                    self._revision += 1
                    self.last_reason = "orbit_recovery_unconfirmed"
                    return self._decision(False, self.last_reason, require_fresh_barrier=True)
            if orbit_probe_only:
                # A newer input revision forbids a normal correction. The
                # bounded recent sample can only gather evidence or request
                # a stop followed by a new, stationary capture/epoch.
                self._revision += 1
                self.last_reason = (
                    "orbit_drift_requires_fresh_handle" if orbit_recovery
                    else "orbit_drift_confirmation_pending" if orbit_candidate
                    else "orbit_motion_probe_no_drift"
                )
                return self._decision(
                    orbit_candidate, self.last_reason,
                    require_fresh_barrier=orbit_recovery,
                    request_orbit_confirmation=orbit_candidate and not orbit_recovery,
                )
            stall_signal = False
            if (
                isinstance(observation, Mapping)
                and observation.get("result") == "ready"
                and actual is not None
                and expected is not None
                and confidence >= HOST_STALL_MIN_CONFIDENCE
                and (current_handle - expected).length
                <= max(3.0, self.visual_max_radius * 0.10)
                and (actual - self.center).length <= self.visual_max_radius + 2.5
            ):
                stall_signal = self._stationary_host_signal(
                    actual, expected, mode, gesture_id
                )
            elif not self.host_stall_pending:
                self._reset_stationary_candidate()
            allow_stall_recovery = stall_signal or self._matches_host_stall(
                actual, mode, confidence, gesture_id
            )
            rejected = self._reject_reason(
                observation,
                current_handle,
                allow_host_stall_recovery=allow_stall_recovery,
                allow_orbit_recovery=orbit_recovery,
            )
            if rejected:
                self.rejections += 1
                self.needs_fresh_handle = True
                # One distant/high-confidence component can still be a false
                # detector choice.  Only an already-established hard event
                # (outer clamp/centre crossing) or the two-sample stationary
                # host signature may stop pointer output.
                require_barrier = self._hard_fresh_required
                if require_barrier:
                    self._center_continuation_blocked = True
                self.last_reason = rejected
                self._revision += 1
                return self._decision(
                    False,
                    rejected,
                    require_fresh_barrier=require_barrier,
                    request_orbit_confirmation=orbit_candidate,
                )

            assert isinstance(observation, Mapping)
            assert actual is not None and expected is not None
            if stall_signal:
                self.host_stall_pending = True
                self._hard_fresh_required = True
                self._center_continuation_blocked = True
                self._host_stall_anchor = actual
                self._host_stall_gesture_id = gesture_id
                self._host_stall_mode = mode
                self.needs_fresh_handle = True
            drift = (actual - expected).length
            self.confirmed = actual
            self._last_observation_actual = actual
            self._last_observation_expected = expected
            self.last_drift_px = drift
            self.confirmations += 1

            queue_idle = abs(float(pending_motion)) <= 1e-9
            correction_trigger = trigger in ("arm_baseline", "gesture_end") or (
                fresh_barrier
                and trigger in (
                    "input_settled",
                    "motion_checkpoint",
                    "motion_settled",
                    "fresh_recovery",
                )
            ) or (orbit_recovery and trigger == "fresh_recovery")
            can_correct = (
                correction_trigger
                and (not orbit_candidate or orbit_recovery)
                and not session_active
                and (queue_idle or fresh_barrier)
                and (current_handle - expected).length
                <= max(1.5, self.visual_max_radius * 0.04)
            )
            correction = self._correction_point(actual, expected, mode)
            preserve_diameter_axis = self._should_preserve_diameter_axis(
                expected,
                mode,
            )
            learned = (
                self._outer_limit_candidate(
                    actual,
                    expected,
                    observation,
                    mode=mode,
                )
                if can_correct
                else None
            )
            center_continued = self._confirm_continuous_center_crossing(
                actual, expected,
                current_handle=current_handle,
                diameter_axis=diameter_axis,
                mode=mode,
                trigger=trigger,
                confidence=confidence,
                session_active=session_active,
                fresh_barrier=fresh_barrier,
                motion_is_current=motion_is_current,
            )
            self.last_reason = (
                "orbit_path_correction_candidate" if orbit_recovery and can_correct
                else "orbit_drift_requires_fresh_handle" if orbit_recovery
                else "orbit_drift_confirmation_pending" if orbit_candidate
                else "host_motion_refused_correction_candidate"
                if can_correct and self.host_stall_pending
                else "correction_candidate"
                if can_correct
                else "host_motion_refused_requires_fresh_handle"
                if self.host_stall_pending
                else "confirmed_center_crossing_continuous"
                if center_continued
                else "confirmed_deferred_until_gesture_end"
            )
            require_barrier = bool(
                self._hard_fresh_required and not can_correct and not center_continued
            )
            if require_barrier:
                # Latch even an otherwise accepted sample which cannot waive
                # the hard event (e.g. confidence .55). A later good sample
                # must not revoke a stop already handed to the engine.
                self._center_continuation_blocked = True
            self._revision += 1

            return self._decision(
                True,
                self.last_reason,
                actual=actual,
                expected=expected,
                correction=correction,
                apply_correction=can_correct,
                learned_max_radius=learned,
                require_fresh_barrier=require_barrier,
                preserve_diameter_axis=preserve_diameter_axis,
                restore_orbit_path=orbit_recovery and can_correct,
                request_orbit_confirmation=orbit_candidate and not orbit_recovery,
            )

    def complete_correction(
        self,
        adopted: Vec2,
        *,
        applied: bool,
        token: int,
        learned_max_radius: Optional[float] = None,
    ) -> bool:
        """Commit only if no pointer/result write superseded ``token``.

        The engine performs its own idle/queue compare before accepting the
        geometry.  This second compare-and-swap protects the feedback-side
        prediction, freshness and probe flags from being overwritten when a
        new pointer event lands between :meth:`consider` and engine reconcile.
        """

        with self._lock:
            if token != self._revision:
                return False
            if not applied:
                self.needs_fresh_handle = True
                self.last_reason = "correction_raced_with_new_motion"
                self._revision += 1
                return False
            # ``confirmed`` remains the raw detector fact. The prediction must
            # instead use the exact (possibly clamped/projected) point adopted
            # by WheelModel so the next burst cannot start from a ghost point.
            self.predicted = adopted
            self.needs_fresh_handle = False
            self.center_crossing_pending = False
            self.outer_probe_pending = False
            self.host_stall_pending = False
            self.no_progress_observations = 0
            self._hard_fresh_required = False
            self._center_continuation_blocked = False
            self._host_stall_anchor = None
            self._host_stall_gesture_id = None
            self._host_stall_mode = ""
            self._reset_stationary_candidate()
            if self._orbit_drift:
                self._orbit_drift.reset()
            self._last_observation_actual = self.confirmed
            self._last_observation_expected = adopted
            self.corrections += 1
            if learned_max_radius is not None:
                learned = max(
                    4.0,
                    min(self.effective_max_radius, float(learned_max_radius)),
                )
                if learned < self.effective_max_radius - 1e-9:
                    self.effective_max_radius = learned
                    self.outer_limit_learns += 1
            self.last_reason = "confirmed_model_checkpoint"
            self._revision += 1
            return True

    def mark_fresh_required(self, reason: str) -> None:
        """Fail closed if an engine barrier could not be released."""

        with self._lock:
            self.needs_fresh_handle = True
            self._hard_fresh_required = True
            self._center_continuation_blocked = True
            self.last_reason = str(reason or "fresh_handle_required")
            self._revision += 1

    def status(self) -> dict:
        with self._lock:
            return {
                "predicted": self._vec_dict(self.predicted),
                "confirmed": self._vec_dict(self.confirmed),
                "needsFreshHandle": self.needs_fresh_handle,
                "centerCrossingPending": self.center_crossing_pending,
                "visualMaxRadius": self.visual_max_radius,
                "effectiveMaxRadius": self.effective_max_radius,
                "outerProbePending": self.outer_probe_pending,
                "lastReason": self.last_reason,
                "lastDriftPx": self.last_drift_px,
                "confirmations": self.confirmations,
                "rejections": self.rejections,
                "corrections": self.corrections,
                "outerLimitLearns": self.outer_limit_learns,
                "hostStallPending": self.host_stall_pending,
                "noProgressObservations": self.no_progress_observations,
                "hardFreshRequired": self._hard_fresh_required,
                "centerContinuations": self.center_continuations,
                "centerContinuationBlocked": self._center_continuation_blocked,
                "revision": self._revision,
                "orbitDriftPending": bool(self._orbit_drift and self._orbit_drift.pending),
                "orbitDriftConfirmations": self._orbit_drift.count if self._orbit_drift else 0,
            }

    def _confirm_continuous_center_crossing(
        self,
        actual: Vec2,
        expected: Vec2,
        *,
        current_handle: Vec2,
        diameter_axis: Optional[Vec2],
        mode: str,
        trigger: str,
        confidence: float,
        session_active: bool,
        fresh_barrier: bool,
        motion_is_current: bool,
    ) -> bool:
        """Acknowledge a healthy crossing without changing held-drag geometry.

        This is not a correction or a barrier release. Only an up-to-date,
        high-confidence sample following the owned diameter can discharge a
        centre-only confirmation. Inside the centre-noise band it only waives
        this sample's UP: keep checking until both points leave that band on
        the same side. Outer probes, refused motion and previously failed
        confirmations still take the original UP/recovery path.
        """

        if (
            not self.center_crossing_pending
            or not self._hard_fresh_required
            or self.outer_probe_pending
            or self.host_stall_pending
            or self._center_continuation_blocked
            or not session_active
            or fresh_barrier
            or not motion_is_current
            or mode != "push_pull"
            or self._last_pointer_mode != "push_pull"
            or not self._push_pull_axis_observed
            or trigger not in (
                "motion_checkpoint", "motion_settled", "input_settled", "fresh_recovery",
            )
            or confidence < HOST_STALL_MIN_CONFIDENCE
            or (current_handle - expected).length > 1e-6
            or (self.predicted - current_handle).length > 1e-6
        ):
            return False
        axis = _point(diameter_axis)
        if axis is None or axis.length <= 1e-9:
            return False
        axis = axis.normalized()
        predicted_offset = expected - self.center
        actual_offset = actual - self.center
        tolerance = max(1.5, self.visual_max_radius * 0.04)
        if (
            abs(axis.x * predicted_offset.y - axis.y * predicted_offset.x) > 1e-6
            or (actual - expected).length > tolerance
            or abs(axis.x * actual_offset.y - axis.y * actual_offset.x) > tolerance
        ):
            return False
        expected_projection = predicted_offset.dot(axis)
        actual_projection = actual_offset.dot(axis)
        if (
            min(abs(expected_projection), abs(actual_projection))
            > WHEEL_DIAMETER_CENTER_STATE_RADIUS
            and expected_projection * actual_projection > 0.0
        ):
            self.center_crossing_pending = False
            self._hard_fresh_required = False
        self.center_continuations += 1
        # Keep needs_fresh_handle and the raw confirmed position. Normal idle
        # feedback will still reconcile onto the existing engine diameter.
        return True

    def _reject_reason(
        self,
        observation: Any,
        current_handle: Vec2,
        *,
        allow_host_stall_recovery: bool = False,
        allow_orbit_recovery: bool = False,
    ) -> str:
        if not isinstance(observation, Mapping) or observation.get("result") != "ready":
            return "observation_not_ready"
        actual = _point(observation.get("actual"))
        expected = _point(observation.get("predicted"))
        if actual is None or expected is None:
            return "observation_point_invalid"
        confidence = self._confidence(observation)
        if not math.isfinite(confidence) or confidence < MIN_CONFIRMATION_CONFIDENCE:
            return "observation_confidence_low"
        actual_offset = actual - self.center
        expected_offset = expected - self.center
        if actual_offset.length > self.visual_max_radius + 2.5:
            return "observation_outside_wheel"
        if (current_handle - expected).length > max(
            3.0, self.visual_max_radius * 0.10
        ):
            return "observation_stale_geometry"
        wrong_side = actual_offset.dot(expected_offset) < 0.0
        far = min(actual_offset.length, expected_offset.length) > max(
            5.0, self.visual_max_radius * 0.22
        )
        trigger = str(observation.get("trigger") or "")
        crossing_authorized = (
            wrong_side
            and far
            and trigger == "gesture_end"
            and self.center_crossing_pending
        )
        if wrong_side and far:
            if not crossing_authorized and not allow_host_stall_recovery:
                return "observation_wrong_side"
            if (
                crossing_authorized
                and not self._opposite_axis_aligned(actual_offset, expected_offset)
                and not allow_host_stall_recovery
            ):
                return "observation_crossing_misaligned"
        drift = (actual - expected).length
        max_drift = max(5.0, self.visual_max_radius * MAX_CORRECTION_DRIFT_RATIO)
        if (
            drift > max_drift
            and not crossing_authorized
            and not allow_host_stall_recovery
            and not allow_orbit_recovery
        ):
            return "observation_drift_too_large"
        return ""

    @staticmethod
    def _confidence(observation: Any) -> float:
        if not isinstance(observation, Mapping):
            return 0.0
        try:
            confidence = float(
                (observation.get("handle") or {}).get("confidence", 0.0)
            )
        except (AttributeError, TypeError, ValueError):
            return 0.0
        return confidence if math.isfinite(confidence) else 0.0

    def _stationary_host_signal(
        self,
        actual: Vec2,
        expected: Vec2,
        mode: str,
        gesture_id: int,
    ) -> bool:
        if mode == "orbit":
            return self._stationary_orbit_signal(
                actual,
                expected,
                mode,
                gesture_id,
            )
        if mode == "push_pull":
            return self._stationary_push_pull_signal(
                actual,
                expected,
                gesture_id,
            )
        self._reset_stationary_candidate()
        return False

    def _stationary_orbit_signal(
        self,
        actual: Vec2,
        expected: Vec2,
        mode: str,
        gesture_id: int,
    ) -> bool:
        """Recognize two same-gesture samples where Resolve stays stationary."""

        trusted_tolerance = max(1.5, self.visual_max_radius * 0.04)
        if (
            mode != "orbit"
            or (actual - self.confirmed).length > trusted_tolerance
        ):
            self._reset_stationary_candidate()
            return False

        if (
            self._stationary_gesture_id != gesture_id
            or self._stationary_mode != mode
            or self._stationary_anchor_actual is None
            or self._stationary_anchor_expected is None
        ):
            self._stationary_gesture_id = gesture_id
            self._stationary_mode = mode
            self._stationary_anchor_actual = (
                self._last_observation_actual or self.confirmed
            )
            self._stationary_anchor_expected = (
                self._last_observation_expected or expected
            )
            self.no_progress_observations = 0

        assert self._stationary_anchor_actual is not None
        assert self._stationary_anchor_expected is not None
        expected_motion = (expected - self._stationary_anchor_expected).length
        actual_motion = (actual - self._stationary_anchor_actual).length
        drift = (actual - expected).length
        if actual_motion > max(
            1.0, self.visual_max_radius * HOST_STALL_MAX_ACTUAL_MOTION_RATIO
        ):
            self._reset_stationary_candidate()
            return False
        self.no_progress_observations += 1
        return (
            self.no_progress_observations >= HOST_STALL_OBSERVATIONS
            and expected_motion
            >= max(2.0, self.visual_max_radius * HOST_STALL_MIN_EXPECTED_MOTION_RATIO)
            and drift
            >= max(3.0, self.visual_max_radius * HOST_STALL_MIN_DRIFT_RATIO)
        )

    def _stationary_push_pull_signal(
        self,
        actual: Vec2,
        expected: Vec2,
        gesture_id: int,
    ) -> bool:
        """Recognize a refused inward pull without confusing an outer clamp.

        Resolve can accept the physical mouse events yet leave an outer handle
        pinned because the new DOWN missed the draggable dot.  Require two
        high-confidence samples from one gesture where the prediction keeps
        moving inward on the same ray while the detected handle remains within
        roughly one pixel of its starting point.  A stationary outward clamp
        has no inward progress and therefore cannot seed this signature.
        """

        trusted_tolerance = max(1.5, self.visual_max_radius * 0.04)
        if (actual - self.confirmed).length > trusted_tolerance:
            self._reset_stationary_candidate()
            return False

        new_candidate = (
            self._stationary_gesture_id != gesture_id
            or self._stationary_mode != "push_pull"
            or self._stationary_anchor_actual is None
            or self._stationary_anchor_expected is None
        )
        if new_candidate:
            self._stationary_gesture_id = gesture_id
            self._stationary_mode = "push_pull"
            self._stationary_anchor_actual = (
                self._last_observation_actual or self.confirmed
            )
            self._stationary_anchor_expected = (
                self._last_observation_expected or expected
            )
            self.no_progress_observations = 0

        assert self._stationary_anchor_actual is not None
        assert self._stationary_anchor_expected is not None
        anchor_actual = self._stationary_anchor_actual
        anchor_expected = self._stationary_anchor_expected
        previous_expected = self._last_observation_expected or anchor_expected
        anchor_offset = anchor_expected - self.center
        previous_offset = previous_expected - self.center
        expected_offset = expected - self.center
        actual_offset = actual - self.center

        # All three points must describe one radial ray.  Besides excluding
        # orbit motion, this prevents a newly selected detector component from
        # being promoted into a host-stall barrier merely because it repeats.
        aligned = (
            anchor_offset.length > 1e-9
            and previous_offset.length > 1e-9
            and expected_offset.length > 1e-9
            and actual_offset.length > 1e-9
            and self._outer_axis_aligned(anchor_offset, previous_offset)
            and self._outer_axis_aligned(anchor_offset, expected_offset)
            and self._outer_axis_aligned(anchor_offset, actual_offset)
            and abs(actual_offset.length - anchor_offset.length)
            <= max(3.0, self.visual_max_radius * 0.08)
        )
        incremental_inward = previous_offset.length - expected_offset.length
        total_inward = anchor_offset.length - expected_offset.length
        actual_motion = (actual - anchor_actual).length
        if (
            not aligned
            or incremental_inward <= 0.05
            or total_inward <= 0.05
            or actual_motion
            > max(1.0, min(1.5, self.visual_max_radius * 0.02))
        ):
            self._reset_stationary_candidate()
            return False

        self.no_progress_observations += 1
        drift = (actual - expected).length
        return (
            self.no_progress_observations >= HOST_STALL_OBSERVATIONS
            and total_inward
            >= max(
                2.0,
                self.visual_max_radius
                * PUSH_PULL_STALL_MIN_EXPECTED_MOTION_RATIO,
            )
            and drift
            >= max(3.0, self.visual_max_radius * PUSH_PULL_STALL_MIN_DRIFT_RATIO)
        )

    def _matches_host_stall(
        self,
        actual: Optional[Vec2],
        mode: str,
        confidence: float,
        gesture_id: int,
    ) -> bool:
        if (
            not self.host_stall_pending
            or self._host_stall_anchor is None
            or actual is None
            or mode != self._host_stall_mode
            or confidence < HOST_STALL_MIN_CONFIDENCE
            or (
                self._host_stall_gesture_id is not None
                and gesture_id != self._host_stall_gesture_id
            )
        ):
            return False
        return (actual - self._host_stall_anchor).length <= max(
            1.5, self.visual_max_radius * 0.04
        )

    @staticmethod
    def _gesture_id(observation: Any) -> int:
        if not isinstance(observation, Mapping):
            return 0
        raw = observation.get("gestureId", 0)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            return 0
        return raw

    def _reset_stationary_candidate(self) -> None:
        self.no_progress_observations = 0
        self._stationary_anchor_actual = None
        self._stationary_anchor_expected = None
        self._stationary_gesture_id = None
        self._stationary_mode = ""

    def _correction_point(
        self,
        actual: Vec2,
        expected: Vec2,
        mode: str,
    ) -> Vec2:
        """Keep an outer radial probe on its established diameter axis."""

        expected_offset = expected - self.center
        actual_offset = actual - self.center

        # A centre orbit cannot physically move the white handle. Likewise,
        # an exact-centre push/pull prediction has no observable pixel angle.
        # Keep the authoritative centre instead of promoting a nearby colour
        # or crosshair component into a new direction.
        if (
            mode in ("orbit", "push_pull", "initial")
            and expected_offset.length <= 1e-9
            and actual_offset.length <= WHEEL_DIAMETER_CENTER_STATE_RADIUS
            and self._should_preserve_diameter_axis(expected, mode)
        ):
            return self.center

        # Near centre, the white-dot centroid has no stable hue direction.  A
        # sub-pixel component must therefore neither replace the model's hidden
        # diameter axis nor erase a real predicted small-radius state.
        if actual_offset.length < CENTER_FEEDBACK_IGNORE_RADIUS:
            if expected_offset.length <= 1e-9:
                return self.center
            return expected

        if self._should_preserve_diameter_axis(expected, mode):
            # Let the engine project the actual coordinate onto its authoritative
            # diameter, including at the rim. Using the pixel vector's length
            # here would convert perpendicular detection error into radial gain.
            return actual

        if (
            not self.outer_probe_pending
            or mode != "push_pull"
            or self._last_pointer_mode != "push_pull"
        ):
            return actual
        if expected_offset.length <= 1e-9 or actual_offset.dot(expected_offset) <= 0.0:
            return actual
        return self.center + expected_offset.normalized() * actual_offset.length

    def _should_preserve_diameter_axis(self, expected: Vec2, mode: str) -> bool:
        """Preserve owned radial axes; orbit remains free to establish a new one."""

        expected_radius = (expected - self.center).length
        return bool(
            (
                mode == "orbit"
                and expected_radius <= WHEEL_DIAMETER_CENTER_STATE_RADIUS
            )
            or (
                mode == "push_pull"
                and (
                    self.center_crossing_pending
                    or self._push_pull_axis_observed
                    or self._preserve_initial_diameter_axis
                )
            )
            or (mode == "initial" and self._preserve_initial_diameter_axis)
        )

    def _outer_limit_candidate(
        self,
        actual: Vec2,
        expected: Vec2,
        observation: Mapping,
        *,
        mode: str,
    ) -> Optional[float]:
        if (
            not self.outer_probe_pending
            or mode != "push_pull"
            or self._last_pointer_mode != "push_pull"
        ):
            return None
        try:
            confidence = float((observation.get("handle") or {}).get("confidence", 0.0))
        except (AttributeError, TypeError, ValueError):
            return None
        actual_offset = actual - self.center
        expected_offset = expected - self.center
        actual_radius = actual_offset.length
        expected_radius = expected_offset.length
        if (
            confidence < 0.55
            or expected_radius < self.visual_max_radius * 0.86
            or actual_radius < self.visual_max_radius * (1.0 - MAX_OUTER_LEARN_INSET_RATIO)
            or expected_radius - actual_radius < 0.35
            or actual_radius >= self.effective_max_radius - 0.15
            or actual_offset.dot(expected_offset) <= 0.0
            or not self._outer_axis_aligned(actual_offset, expected_offset)
        ):
            return None
        return max(4.0, min(self.effective_max_radius, actual_radius + 0.25))

    def _outer_axis_aligned(self, actual: Vec2, expected: Vec2) -> bool:
        """Require an outer refusal to remain on the predicted radial ray."""

        actual_radius = actual.length
        expected_radius = expected.length
        if actual_radius <= 1e-9 or expected_radius <= 1e-9:
            return False
        cosine = actual.dot(expected) / (actual_radius * expected_radius)
        perpendicular = abs(expected.x * actual.y - expected.y * actual.x) / expected_radius
        return (
            cosine >= math.cos(math.radians(MAX_OUTER_ALIGNMENT_DEGREES))
            and perpendicular <= max(1.0, self.visual_max_radius * 0.025)
        )

    def _opposite_axis_aligned(self, actual: Vec2, expected: Vec2) -> bool:
        """Allow a confirmed center crossing only near the same diameter."""

        actual_radius = actual.length
        expected_radius = expected.length
        if actual_radius <= 1e-9 or expected_radius <= 1e-9:
            return False
        cosine = actual.dot(expected) / (actual_radius * expected_radius)
        perpendicular = abs(expected.x * actual.y - expected.y * actual.x) / expected_radius
        return (
            cosine <= -math.cos(math.radians(MAX_CROSSING_ALIGNMENT_DEGREES))
            and perpendicular <= max(1.5, self.visual_max_radius * 0.05)
        )

    def _decision(
        self,
        accepted: bool,
        reason: str,
        *,
        actual: Optional[Vec2] = None,
        expected: Optional[Vec2] = None,
        correction: Optional[Vec2] = None,
        apply_correction: bool = False,
        learned_max_radius: Optional[float] = None,
        require_fresh_barrier: bool = False,
        preserve_diameter_axis: bool = False,
        restore_orbit_path: bool = False,
        request_orbit_confirmation: bool = False,
    ) -> dict:
        return {
            "accepted": bool(accepted),
            "reason": reason,
            "actual": self._vec_dict(actual),
            "expected": self._vec_dict(expected),
            "correction": self._vec_dict(correction),
            "applyCorrection": bool(apply_correction),
            "learnedMaxRadius": learned_max_radius,
            "requireFreshBarrier": bool(require_fresh_barrier),
            "preserveDiameterAxis": bool(preserve_diameter_axis),
            "restoreOrbitPath": bool(restore_orbit_path),
            "requestOrbitConfirmation": bool(request_orbit_confirmation),
            "correctionToken": self._revision if apply_correction else None,
            "state": self.status(),
        }

    @staticmethod
    def _vec_dict(value: Optional[Vec2]) -> Optional[dict]:
        if value is None:
            return None
        return {"x": float(value.x), "y": float(value.y)}


__all__ = ["WheelFeedbackState"]
