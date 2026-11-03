"""Windows transport using the shared tagged-button lifecycle.

QuartzGestureSink's cancellation, deferred DOWN and failsafe ownership are
platform independent. This adapter replaces its coordinate and edge policies;
it never sends the macOS-only off-screen rebase sentinel to Windows.
"""

import math
import os
import secrets
from dataclasses import dataclass

from .geometry import Vec2
from .interlock import InputInterlock
from .macos import MacOSBindings
from .quartz_sink import QuartzGestureSink, POST_EDGE_MARGIN, RESOLVE_LOCATION_SCALE
from .sinks import TransportStep


# Match the new continuous absolute trajectory, including its transport gain.
# Under-scaling displacements about the initial handle produces a smaller,
# off-centre host orbit; changing cadence/angle cannot correct that geometry.
WINDOWS_LOCATION_SCALE = RESOLVE_LOCATION_SCALE
WINDOWS_EDGE_MARGIN = 100.0
CURSOR_POLL = .002
CURSOR_SETTLE = 1.0 / 120.0
# Release and press require host capture qualification plus cursor stability.
# No fixed sleep substitutes for observing the host's actual capture transition.
RELEASE_SETTLE = CURSOR_SETTLE
RECOVERY_PHASE_TIMEOUT = .100
RECOVERY_TIMEOUT = .250
RESTORE_WINDOW = .250
# The trace includes a delayed return 3.2px from the preceding DOWN. Permit
# that small host landing offset only during our own recent UP/DOWN recovery;
# external hook events still cancel regardless of distance.
RESTORE_POINT_TOLERANCE = 6.0
CAPTURE_TRACE_VERSION = 'windows-capture.1'
CAPTURE_GATE_VERSION = 'windows-capture-gate.2'


class _CursorOriginChanged(Exception):
    def __init__(self, position):
        self.position = position


@dataclass
class _WindowsPending:
    phase: str
    position: Vec2
    logical: object
    origin: Vec2
    previous_event: Vec2
    started_at: float
    phase_started_at: float
    next_deadline: float
    candidate: object = None
    stable_since: float = 0.0
    edge: bool = False
    landing: object = None
    positioned: bool = False
    capture_key: object = None
    capture_since: float = 0.0
    capture_status: str = 'unknown'


class WindowsInputInterlock(InputInterlock):
    # Win32 reports integral pixels, including physical monitor coordinates.
    CONFIRMATION_POSITION_TOLERANCE = 1.5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The live Windows input route truncates dwExtraInfo to its low DWORD
        # before WH_MOUSE_LL observes it, even in the bundled 64-bit Python.
        # A shared 62-bit tag therefore misclassifies our own DOWN as external
        # input and cancels before DRAG. Keep the entire tag in that DWORD.
        self.tag = secrets.randbelow(2**32 - 1) + 1
        self._native_down_record = None
        self._native_down_confirmation = None

    def _confirm_tagged_unlocked(self, event_type, position, timestamp):
        result = super()._confirm_tagged_unlocked(event_type, position, timestamp)
        if event_type == MacOSBindings.LEFT_DOWN and result['coveredPosts']:
            self._native_down_record = (tuple(position), float(timestamp))
            self._native_down_confirmation = (
                tuple(position), float(timestamp), result['coveredThroughSequence'])
        return result

    def native_down_record(self):
        with self._lock:
            return self._native_down_record

    def native_down_confirmation(self):
        with self._lock:
            return self._native_down_confirmation

    def posted_sequence(self):
        with self._lock:
            return self._post_sequence

    @classmethod
    def _positions_match(cls, pending, observed):
        if pending.kind in ('down', 'up'):
            # Windows can deliver our tagged button at the host-restored cursor
            # location, different from the MOVE in the same SendInput. The
            # ordered same-kind/tag callback confirms button delivery only.
            # The sink separately validates the actual origin before any drag.
            try:
                return all(math.isfinite(float(observed[i])) for i in (0, 1))
            except (TypeError, ValueError, IndexError):
                return False
        return super()._positions_match(pending, observed)


class WindowsGestureSink(QuartzGestureSink):
    def __init__(self, *args, **kwargs):
        self._windows_down_point = None
        self._windows_down_at = float('-inf')
        self._windows_pending = None
        self._windows_restore_points = []
        self._windows_burst_origin = None
        self._windows_release_origin = None
        self._windows_reanchor_until = float('-inf')
        self._windows_press_sequence = 0
        self._windows_capture_until = float('-inf')
        self._windows_capture_next_sample = float('-inf')
        self._windows_capture_last_state = None
        self._windows_capture_last_emit = float('-inf')
        self._windows_origin_trace_key = None
        self._windows_last_up_at = float('-inf')
        self._windows_gate_trace_key = None
        self._windows_press_landing = None
        self._windows_press_post_sequence = None
        self._native_cursor_diagnostics = os.environ.get(
            'DAVINCI_WINDOWS_MOTION_TRACE', '1'
        ).lower() not in {'0', 'false', 'no', 'off'}
        kwargs.update(detach_cursor=False, observe_rebase_origin=False)
        super().__init__(*args, **kwargs)
        previous = getattr(self._bindings, '_last_wheel_down', None)
        if previous is not None:
            point, self._windows_down_at = previous
            self._windows_down_point = Vec2(*point)

    @classmethod
    def calculate_location_scale(cls, requested, anchor, display_bounds,
                                 logical_bounds=None, edge_margin=0.0):
        if not math.isfinite(requested) or requested <= 0:
            raise ValueError("invalid Windows transport scale")
        bounds = cls._normalize_bounds(display_bounds)
        safe = cls._inset_bounds(bounds, POST_EDGE_MARGIN)
        if safe is None or anchor is None:
            raise ValueError("Windows drag requires a monitor and an anchor")
        x, y, w, h = safe
        if w <= 0 or h <= 0 or not (x <= anchor.x <= x + w and y <= anchor.y <= y + h):
            raise ValueError("Windows anchor is outside its monitor")
        return {"enabled": True, "resolved": True, "requested": requested,
                "effective": requested, "attenuated": False,
                "strategy": "win32_absolute_pixel_mapping",
                "edgeMargin": WINDOWS_EDGE_MARGIN, "postEdgeMargin": POST_EDGE_MARGIN,
                "rebaseWhileDown": False, "rebaseTarget": "inside_wheel",
                "rebaseTransport": "win32_verified_origin_continue",
                "outOfBoundsDragEvents": False, "outOfBoundsDragScope": None,
                "hostReanchorSemantics": "preserve_model_and_pending_motion",
                "restoreAfterIdleUp": False, "anchor": cls._vec_dict(anchor),
                "displayBounds": cls._rect_dict(bounds), "safeBounds": cls._rect_dict(safe),
                "rebaseBounds": cls._rect_dict(cls._inset_bounds(bounds, WINDOWS_EDGE_MARGIN)),
                "wheelBounds": cls._rect_dict(logical_bounds)}

    def _resolve_location_scale(self, initial_anchor):
        return self.calculate_location_scale(self._requested_location_scale, initial_anchor,
                                             self._display_bounds, self._logical_bounds)

    def _point_requires_rebase(self, position):
        # The adapter handles continuation before entering the Quartz path.
        return not self._point_is_safe(position)

    def _prepare_rebase(self, requested):
        raise RuntimeError("windows_reanchor_geometry_unsafe")

    def _double_click_risk(self, point):
        self._refresh_native_down_record()
        previous = self._windows_down_point
        if previous is None or self._clock() - self._windows_down_at > self._bindings.double_click_interval():
            return False
        size = getattr(self._bindings, 'double_click_size', lambda: (4, 4))()
        # Use the full rectangle dimensions plus a pixel-rounding margin.
        return abs(point.x - previous.x) <= size[0] + 2 and abs(point.y - previous.y) <= size[1] + 2

    def _refresh_native_down_record(self):
        record = self._interlock.native_down_record()
        if record is not None:
            point, timestamp = record
            if timestamp >= self._windows_down_at:
                self._windows_down_point = Vec2(*point)
                self._windows_down_at = timestamp
                self._bindings._last_wheel_down = record

    def _continuation_anchor(self, logical_origin, target, preferred=None, *, maximize_runway=False):
        if self._logical_bounds is None:
            raise RuntimeError("windows_reanchor_requires_wheel_geometry")
        left, top, width, height = self._logical_bounds
        center = Vec2(left + width / 2, top + height / 2)
        radius = min(width, height) / 2 - 5
        if radius <= 0:
            raise RuntimeError("windows_reanchor_wheel_too_small")
        offset = logical_origin - center
        first = center + offset.normalized() * min(offset.length, radius) if offset.length else center
        candidates = [preferred or first, first, center]
        # Alternate interior landings avoid rapid same-position double clicks.
        for x, y in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            candidates.append(center + Vec2(x, y).normalized() * radius * .65)
        displacement = (target - logical_origin) * self._location_scale
        safe_candidates = []
        for candidate in candidates:
            candidate = self._pixel(candidate)
            endpoint = self._pixel(candidate + displacement)
            if ((candidate - center).length <= radius + .01 and
                    self._roomy(candidate) and self._roomy(endpoint) and
                    not self._double_click_risk(candidate)):
                if not maximize_runway:
                    return candidate, endpoint
                safe_candidates.append((candidate, endpoint))
        if safe_candidates:
            selected = max(safe_candidates, key=lambda pair: self._runway(pair[0], displacement))
            self._trace_control('windows_edge_landing', 'directional_screen_room', True,
                                from_position=safe_candidates[0][0], to_position=selected[0],
                                logical_position=logical_origin,
                                details={'firstCandidateRunwayPx': self._runway(safe_candidates[0][0], displacement),
                                         'selectedRunwayPx': self._runway(selected[0], displacement)})
            return selected
        raise RuntimeError("windows_reanchor_no_safe_landing")

    def _runway(self, anchor, displacement):
        direction = displacement.normalized()
        x, y, w, h = self._display_bounds
        distances = []
        for value, component, lower, upper in (
                (anchor.x, direction.x, x + WINDOWS_EDGE_MARGIN, x + w - 1 - WINDOWS_EDGE_MARGIN),
                (anchor.y, direction.y, y + WINDOWS_EDGE_MARGIN, y + h - 1 - WINDOWS_EDGE_MARGIN)):
            if component > 1e-9:
                distances.append((upper - value) / component)
            elif component < -1e-9:
                distances.append((lower - value) / component)
        return min(distances) if distances else 0.0

    def _continue_at_edge(self, position, logical):
        origin = self._last_logical_position
        anchor, _ = self._continuation_anchor(origin, position, maximize_runway=True)
        self._validate_display(anchor)
        if not self._down:
            # No old native segment exists, so there is nothing to release.
            self._mapping_logical_anchor = origin
            self._mapping_event_anchor = anchor
            self._last_event_position = anchor
            return self._send_motion(position, logical)
        old_event = self._last_event_position
        if self._windows_down_point is not None:
            self._windows_restore_points.append(self._windows_down_point)
            self._windows_restore_points = self._windows_restore_points[-4:]
        # Resolve also restores to the logical handle at release, rather than
        # to a native DOWN. Keep it even when the double-click guard chose a
        # different physical landing (PID25124 at 02:10:43.277).
        self._windows_release_origin = origin
        self._windows_reanchor_until = self._clock() + RESTORE_WINDOW
        # Keep logical ownership: native UP must not start an idle scan.
        if not self._post('up', old_event, 'windows_edge_release', trace_kind='windows_reanchor_up'):
            return
        if self._cancelled():
            return
        now = self._clock()
        pending = _WindowsPending(
            'release', position, logical, origin, old_event, now, now,
            now + CURSOR_POLL, edge=True, landing=anchor)
        self._windows_pending = pending
        # Resolve may still own the old drag after SendInput acknowledges UP.
        # Do not relocate or press again until its GUI capture has released.

    def _position_landing(self, pending, anchor):
        # MOVE while native UP is a separate event. Observe the landing before
        # sending a stationary DOWN, so host UP restoration cannot be hidden
        # between MOVE and DOWN of a single combined SendInput call.
        self._validate_display(anchor)
        if not self._post('move', anchor, 'windows_edge_position', trace_kind='windows_reanchor_move'):
            self._windows_pending = None
            return False
        self._last_event_position = anchor
        pending.landing = anchor
        pending.positioned = True
        pending.candidate = None
        pending.next_deadline = self._clock() + CURSOR_POLL
        return True

    def _validate_display(self, point):
        resolver = getattr(self._bindings, 'display_bounds_for_point', None)
        if not callable(resolver) or tuple(resolver((point.x, point.y))) != tuple(self._display_bounds):
            raise RuntimeError("windows_reanchor_display_changed")

    def _roomy(self, point):
        return self._edge_distance(point) >= WINDOWS_EDGE_MARGIN

    def _edge_distance(self, point):
        x, y, w, h = self._display_bounds
        return min(point.x - x, x + w - 1 - point.x,
                   point.y - y, y + h - 1 - point.y)

    def _cancelled(self):
        if self._interlock.cancel_reason:
            self.emergency_release(self._interlock.cancel_reason)
        if self._release_requested.is_set():
            self._windows_pending = None
            return True
        return False

    def _known_origin_change(self, actual):
        if not self._point_is_safe(actual):
            return False
        x, y, w, h = self._display_bounds
        center = Vec2(x + w / 2, y + h / 2)
        recent_reanchor = self._clock() <= self._windows_reanchor_until
        central = (actual - center).length <= 64
        if central and (not self._roomy(self._last_event_position) or recent_reanchor):
            return True
        return recent_reanchor and any(
            point is not None and (actual - point).length <= RESTORE_POINT_TOLERANCE
            for point in [*self._windows_restore_points, self._windows_burst_origin,
                          self._windows_release_origin])

    def _stage_origin_change(self, position, logical, actual, pending=None):
        if self._cancelled():
            return
        if not self._known_origin_change(actual):
            self._trace_origin_sample('stage_rejected', actual, pending, force=True)
            raise RuntimeError('windows_unexpected_cursor_origin')
        now = self._clock()
        if pending is None:
            self._windows_reanchor_until = now + RESTORE_WINDOW
            pending = _WindowsPending('origin', position, logical,
                                      self._last_logical_position, self._last_event_position,
                                      now, now, now + CURSOR_POLL)
        else:
            # Keep the original total deadline even after multiple migrations.
            if pending.phase != 'origin':
                pending.phase_started_at = now
            pending.phase = 'origin'
            pending.next_deadline = now + CURSOR_POLL
        pending.candidate = actual
        pending.stable_since = now
        self._windows_pending = pending
        self._trace_origin_sample('origin_staged', actual, pending, force=True)

    def next_transport_deadline(self):
        with self._lock:
            pending = self._windows_pending
            return None if self._release_requested.is_set() or pending is None else pending.next_deadline

    def model_output_ready(self):
        """Clearing a cancelled transport is not a receipt for its held frame."""
        with self._lock:
            return (not self._release_requested.is_set() and
                    not self._interlock.cancel_reason and self._windows_pending is None)

    def _location_scale_status_unlocked(self):
        result = super()._location_scale_status_unlocked()
        pending = self._windows_pending
        result.update(rebasePending=pending is not None,
                      rebasePhase=None if pending is None else pending.phase,
                      rebaseNextDeadline=None if pending is None else pending.next_deadline,
                      rebaseCursorVersion='windows-origin.5', observeRebaseOrigin=True,
                      captureTraceVersion=CAPTURE_TRACE_VERSION,
                      captureGateVersion=CAPTURE_GATE_VERSION,
                      windowsReleaseSettleMs=RELEASE_SETTLE * 1000,
                      windowsCursorSettleMs=CURSOR_SETTLE * 1000,
                      windowsOriginTimeoutMs=RECOVERY_TIMEOUT * 1000,
                      windowsPhaseTimeoutMs=RECOVERY_PHASE_TIMEOUT * 1000)
        return result

    def _mark_released(self):
        self._windows_pending = None
        self._windows_press_landing = None
        self._windows_press_post_sequence = None
        self._windows_burst_origin = None
        self._windows_release_origin = None
        self._windows_restore_points = []
        self._windows_reanchor_until = float('-inf')
        super()._mark_released()

    def _discard_pending_session(self):
        self._windows_pending = None
        self._windows_press_landing = None
        self._windows_press_post_sequence = None
        self._windows_burst_origin = None
        self._windows_release_origin = None
        self._windows_restore_points = []
        self._windows_reanchor_until = float('-inf')
        super()._discard_pending_session()

    def _begin_physical_down_unlocked(self, anchor):
        self._windows_burst_origin = self._pixel(anchor)
        # Do not whitelist an unvalidated actual DOWN as a burst origin.
        return super()._begin_physical_down_unlocked(anchor)

    def up(self, position, timestamp, reason='idle'):
        with self._lock:
            pending = self._windows_pending
            if pending is not None and pending.phase == 'release' and not self._physical_down.is_set():
                # Initial capture wait owns the logical session only. A normal
                # timeout/reset must not release someone else's native button.
                self._mark_released()
                self._discard_pending_session()
                return
            return super().up(position, timestamp, reason)

    def _capture_status(self):
        """Mandatory host-state read, independent of optional trace switches."""
        target_pid = getattr(self._source, 'target_pid', None)
        try:
            sample = self._bindings.mouse_capture_state(target_pid=target_pid)
            foreground = sample.get('foreground') or {}
            target = sample.get('target') or {}
            gui = target.get('gui') or {}
            valid = (target_pid is not None and sample.get('ok') is True and not sample.get('errors') and
                     foreground.get('pid') == target_pid and
                     target.get('pid') == target_pid and gui.get('ok') and
                     target.get('threadId') and target.get('hwnd') and
                     foreground.get('threadId') == target.get('threadId') and
                     foreground.get('hwnd') == target.get('hwnd'))
            capture = gui.get('hwndCapture')
            status = 'unknown'
            if valid and capture == 0:
                status = 'released'
            elif (valid and capture and gui.get('capturePid') == target_pid and
                  gui.get('captureThreadId') == target.get('threadId')):
                status = 'held'
            identity = (target.get('pid'), target.get('threadId'), target.get('hwnd'), capture)
        except Exception as exc:
            status, identity = 'unknown', None
            sample = {'errors': ['%s: %s' % (type(exc).__name__, exc)]}
        key = (status, identity)
        if key != self._windows_gate_trace_key:
            self._windows_gate_trace_key = key
            self._trace_control('windows_capture_gate', status, status != 'unknown',
                                details={'version': CAPTURE_GATE_VERSION, 'sample': sample})
        return status, identity

    def _capture_ready(self, pending, expected):
        status, identity = self._capture_status()
        pending.capture_status = status
        if status != expected:
            pending.capture_key = None
            pending.candidate = None
            if pending.phase == 'release':
                pending.positioned = False
            return False
        key = (status, identity)
        if pending.capture_key != key:
            pending.capture_key = key
            pending.capture_since = self._clock()
            pending.candidate = None
        return self._clock() - pending.capture_since >= CURSOR_SETTLE

    def _stage_initial_press(self, position, logical, phase):
        now = self._clock()
        if phase == 'release' and now - self._windows_last_up_at <= RESTORE_WINDOW:
            # Idle UP clears the old session's candidates. Restore only our
            # recent release history for this bounded re-press, not arbitrary
            # cursor positions or a fresh 250ms window on each retry.
            self._windows_reanchor_until = self._windows_last_up_at + RESTORE_WINDOW
            self._windows_release_origin = self._last_logical_position
            if self._windows_down_point is not None:
                self._windows_restore_points.append(self._windows_down_point)
                self._windows_restore_points = self._windows_restore_points[-4:]
        if not self._down:
            # Retain logical ownership while physical UP, just as at the edge.
            self._down = True
            self._interlock.set_owner_down(True)
            self._state_callback(True)
        self._windows_pending = _WindowsPending(
            phase, position, logical, self._last_logical_position,
            self._last_event_position, now, now, now + CURSOR_POLL,
            landing=self._pixel(self._last_event_position))

    def _retry_release_origin(self, pending, actual):
        # No native DOWN was posted. Keep the pending frame and total deadline;
        # an origin-phase retry would incorrectly treat logical ownership as DOWN.
        if not self._known_origin_change(actual):
            raise RuntimeError('windows_unexpected_cursor_origin')
        pending.phase = 'release'
        pending.positioned = False
        pending.candidate = None
        pending.capture_key = None
        pending.next_deadline = self._clock() + CURSOR_POLL
        self._trace_origin_sample('release_origin_retry', actual, pending, force=True)

    def _confirmed_press_position(self):
        record = self._interlock.native_down_confirmation()
        if record is None or record[2] != self._windows_press_post_sequence:
            return None
        return Vec2(*record[0])

    def _press_origin_valid(self, actual):
        confirmed = self._confirmed_press_position()
        landing = self._windows_press_landing
        return (confirmed is not None and landing is not None and
                (confirmed - landing).length <= 1.5 and (actual - landing).length <= 1.5)

    def _retry_changed_press(self, pending, actual):
        """Release a misplaced DOWN; never reinterpret it as a valid drag."""
        confirmed = self._confirmed_press_position()
        landing = self._windows_press_landing
        for point in (confirmed, actual):
            if point is None or (landing is not None and (point - landing).length <= 1.5):
                continue
            known_release = (point - pending.origin).length <= RESTORE_POINT_TOLERANCE
            if not self._point_is_safe(point) or not (known_release or self._known_origin_change(point)):
                self._trace_origin_sample('stage_rejected', point, pending, force=True)
                raise RuntimeError('windows_unexpected_cursor_origin')
        if self._cancelled():
            return False
        self._trace_control('windows_press_landing_retry', 'actual_down_or_origin_changed', False,
                            from_position=landing, to_position=actual,
                            logical_position=pending.position,
                            details={'version': CAPTURE_GATE_VERSION,
                                     'confirmedDown': self._vec_dict(confirmed),
                                     'requestedDown': self._vec_dict(landing),
                                     'downPostSequence': self._windows_press_post_sequence,
                                     'elapsedMs': (self._clock() - pending.started_at) * 1000})
        if not self._post('up', actual, 'windows_press_landing_retry', trace_kind='windows_repress_up'):
            return False
        if self._cancelled():
            return False
        now = self._clock()
        self._windows_release_origin = pending.origin
        # The pending recovery keeps its original hard deadline across retries.
        self._windows_reanchor_until = min(now + RESTORE_WINDOW, pending.started_at + RECOVERY_TIMEOUT)
        anchor, _ = self._continuation_anchor(pending.origin, pending.position,
                                               preferred=pending.landing,
                                               maximize_runway=pending.edge)
        pending.phase = 'release'
        pending.phase_started_at = now
        pending.landing = anchor
        pending.positioned = False
        pending.candidate = None
        pending.capture_key = None
        pending.capture_status = 'unknown'
        pending.next_deadline = now + CURSOR_POLL
        self._windows_pending = pending
        return True

    def service_transport(self, timestamp):
        if not math.isfinite(timestamp):
            raise ValueError('transport timestamp must be finite')
        with self._lock:
            pending = self._windows_pending
            if pending is None:
                return TransportStep(False)
            if self._cancelled() or not self._down:
                self._windows_pending = None
                return TransportStep(True, 'cancelled', cancelled=True)
            if timestamp < pending.next_deadline:
                return TransportStep(True, pending.phase, pending.next_deadline)
            actual = None
            try:
                now = self._clock()
                total_expired = now - pending.started_at >= RECOVERY_TIMEOUT
                phase_expired = now - pending.phase_started_at >= RECOVERY_PHASE_TIMEOUT
                if total_expired or phase_expired:
                    raise RuntimeError('windows_cursor_origin_timeout:%s:%s:capture_%s' %
                                       ('total' if total_expired else 'phase', pending.phase, pending.capture_status))
                actual = Vec2(*self._bindings.current_mouse_position())
                self._trace_origin_sample('transport_poll', actual, pending)
                self._validate_display(actual)
                if pending.phase == 'press':
                    if self._confirmed_press_position() is None:
                        # A provisional cursor read is not a delivered DOWN.
                        pending.candidate = None
                        pending.capture_key = None
                        pending.next_deadline = self._clock() + CURSOR_POLL
                        return TransportStep(True, 'press_confirmation', pending.next_deadline)
                    if not self._press_origin_valid(actual):
                        if not self._retry_changed_press(pending, actual):
                            return TransportStep(True, 'cancelled', cancelled=True)
                        return TransportStep(True, 'release', pending.next_deadline)
                expected_capture = 'released' if pending.phase == 'release' else 'held'
                capture_stable = self._capture_ready(pending, expected_capture)
                if pending.capture_key is None or (pending.phase == 'release' and not capture_stable):
                    pending.next_deadline = self._clock() + CURSOR_POLL
                    return TransportStep(True, pending.phase, pending.next_deadline)
                if pending.phase == 'release' and not pending.positioned:
                    if not self._position_landing(pending, pending.landing):
                        return TransportStep(True, 'cancelled', cancelled=True)
                    return TransportStep(True, 'position', pending.next_deadline)
                if pending.phase == 'release' and (actual - pending.landing).length > 1.5:
                    if not self._known_origin_change(actual):
                        raise RuntimeError('windows_unexpected_cursor_origin')
                    if not self._position_landing(pending, pending.landing):
                        return TransportStep(True, 'cancelled', cancelled=True)
                    return TransportStep(True, 'position', pending.next_deadline)
                if pending.phase != 'release' and (actual - self._pixel(self._last_event_position)).length > 1.5:
                    if not self._known_origin_change(actual):
                        raise RuntimeError('windows_unexpected_cursor_origin')
                if pending.candidate is None or (actual - pending.candidate).length > 1.5:
                    pending.candidate = actual
                    pending.stable_since = now
                stable = now - pending.stable_since >= CURSOR_SETTLE
                released_long_enough = now - pending.phase_started_at >= RELEASE_SETTLE
                if not stable or not capture_stable or (pending.phase == 'release' and not released_long_enough):
                    pending.next_deadline = now + CURSOR_POLL
                    return TransportStep(True, pending.phase, pending.next_deadline)
                if self._cancelled():
                    return TransportStep(True, 'cancelled', cancelled=True)
                if pending.phase == 'release':
                    anchor = pending.landing
                    if self._double_click_risk(actual):
                        anchor, _ = self._continuation_anchor(pending.origin, pending.position, maximize_runway=True)
                        if not self._position_landing(pending, anchor):
                            return TransportStep(True, 'cancelled', cancelled=True)
                        return TransportStep(True, 'position', pending.next_deadline)
                    self._validate_display(anchor)
                    self._mapping_logical_anchor = pending.origin
                    self._mapping_event_anchor = anchor
                    self._last_event_position = anchor
                    self._trace_origin_sample('release_stable_before_down', actual, pending, force=True)
                    # Re-read after diagnostics/position checks. Qualification
                    # from an earlier poll must not survive a capture transition.
                    if not self._capture_ready(pending, 'released'):
                        pending.next_deadline = self._clock() + CURSOR_POLL
                        return TransportStep(True, 'release', pending.next_deadline)
                    try:
                        posted = self._post('down', anchor, 'windows_edge_reanchor',
                                            trace_kind='windows_reanchor_down', stationary_down=True)
                    except _CursorOriginChanged as changed:
                        actual = changed.position
                        self._retry_release_origin(pending, actual)
                        return TransportStep(True, 'release', pending.next_deadline)
                    if not posted:
                        self._windows_pending = None
                        return TransportStep(True, 'cancelled', cancelled=True)
                    self._windows_restore_points.append(anchor)
                    self._windows_restore_points = self._windows_restore_points[-4:]
                    pending.phase = 'press'
                    pending.phase_started_at = self._clock()
                    pending.candidate = None
                    pending.capture_key = None
                    pending.next_deadline = pending.phase_started_at + CURSOR_POLL
                    return TransportStep(True, 'press', pending.next_deadline)
                # Adopt the measured origin at the last committed logical point.
                # The engine already consumed the staged frame; do not requeue it.
                self._trace_origin_sample('origin_stable_before_drag', actual, pending, force=True)
                if not self._capture_ready(pending, 'held'):
                    pending.next_deadline = self._clock() + CURSOR_POLL
                    return TransportStep(True, pending.phase, pending.next_deadline)
                self._mapping_logical_anchor = pending.origin
                self._mapping_event_anchor = actual
                self._last_event_position = actual
                endpoint = self._event_position(pending.position)
                if not self._point_is_safe(endpoint):
                    raise RuntimeError('windows_recovered_endpoint_unsafe')
                self._windows_pending = None
                try:
                    self._send_motion(pending.position, pending.logical)
                except _CursorOriginChanged as changed:
                    # The final guard can observe a newer position than this
                    # poll. Preserve the rejected sample if staging it fails.
                    actual = changed.position
                    if pending.phase == 'press':
                        if not self._retry_changed_press(pending, actual):
                            return TransportStep(True, 'cancelled', cancelled=True)
                    else:
                        self._stage_origin_change(pending.position, pending.logical, changed.position, pending)
                    return TransportStep(True, pending.phase, pending.next_deadline)
                if self._cancelled():
                    return TransportStep(True, 'cancelled', cancelled=True)
                self._rebase_count += 1
                self._burst_rebase_count += 1
                self._trace_control('windows_edge_continue' if pending.edge else 'windows_origin_recovered',
                                    'verified_native_origin', True,
                                    from_position=pending.previous_event, to_position=self._last_event_position,
                                    logical_position=pending.position,
                                    details={'version': 'windows-origin.5',
                                             'logicalOrigin': self._vec_dict(pending.origin),
                                             'nativeAnchor': self._vec_dict(actual),
                                             'elapsedMs': (self._clock() - pending.started_at) * 1000})
                return TransportStep(True, 'motion', completed=True)
            except Exception as exc:
                failure_details = self._origin_diagnostic_details(actual, pending)
                self._trace_origin_sample('recovery_failed', actual, pending, force=True)
                self._windows_pending = None
                self._trace_control('windows_origin_recovery_failed', 'recovery_aborted', False,
                                    logical_position=pending.position, error=str(exc),
                                    details=failure_details)
                self._interlock.mark_cancel('windows_origin_recovery_failed')
                self.emergency_release('windows_origin_recovery_failed')
                raise

    def _send_motion(self, position, logical):
        endpoint = self._event_position(position)
        new_press = not self._down
        if not self._point_is_safe(endpoint):
            raise RuntimeError('windows_motion_endpoint_unsafe')
        if not self._down:
            status, _ = self._capture_status()
            recent_up = self._clock() - self._windows_last_up_at <= RESTORE_WINDOW
            if status != 'released' or recent_up:
                self._stage_initial_press(position, logical, 'release')
                return
            if not self._begin_physical_down_unlocked(self._last_event_position):
                return
            status, _ = self._capture_status()
            actual = Vec2(*self._bindings.current_mouse_position())
            if status != 'held' or not self._press_origin_valid(actual):
                self._stage_initial_press(position, logical, 'press')
                if self._confirmed_press_position() is not None and not self._press_origin_valid(actual):
                    self._retry_changed_press(self._windows_pending, actual)
                return
        if not self._physical_down.is_set():
            raise RuntimeError('windows_drag_without_physical_down')
        requested = position - self._last_logical_position
        relative = {'requested': (requested.x, requested.y), 'postedEventFields': (0, 0),
                    'scaledLocationDelta': (requested.x * self._location_scale, requested.y * self._location_scale)}
        try:
            posted = self._post('drag', endpoint, 'gesture_update', relative_delta=relative, logical=logical)
        except _CursorOriginChanged as changed:
            if not new_press:
                raise
            self._stage_initial_press(position, logical, 'press')
            self._retry_changed_press(self._windows_pending, changed.position)
            return
        if posted:
            self._last_logical_position = position
            self._last_event_position = endpoint
            self._model_position = position

    @staticmethod
    def _pixel(position):
        return Vec2(float(round(position.x)), float(round(position.y)))

    def _drag_absolute_unlocked(self, position, logical=None, safe_press_mode=None):
        if self._cancelled():
            return
        if self._windows_pending is not None:
            raise RuntimeError('windows cursor transport is pending')
        if logical and logical.get('crossedCenter'):
            before = Vec2(*logical['before'])
            applied = logical['applied']
            axis = (position - before) * (1.0 / applied) if applied else None
            self._trace_control('windows_center_crossing', 'logical_model_step', True,
                                from_position=before, to_position=position,
                                logical_position=position,
                                details={'mode': logical['mode'],
                                         'diameterAxis': self._vec_dict(axis),
                                         'applied': applied,
                                         'nativeBefore': self._vec_dict(self._last_event_position)})
        if safe_press_mode is not None:
            self._apply_outer_safe_press_unlocked(safe_press_mode)
        if not self._down and self._double_click_risk(self._pixel(self._mapping_event_anchor)):
            old_anchor = self._mapping_event_anchor
            anchor, _ = self._continuation_anchor(
                self._mapping_logical_anchor, position, self._mapping_event_anchor)
            self._mapping_event_anchor = anchor
            self._last_event_position = anchor
            self._trace_control('windows_press_reanchor', 'double_click_guard', True,
                                from_position=old_anchor, to_position=anchor,
                                logical_position=self._mapping_logical_anchor)
        endpoint = self._pixel(self._event_position(position))
        previous = self._pixel(self._last_event_position)
        if endpoint == previous:
            # Keep the floating model and absolute origin. Repeated fractional
            # frames eventually reach the next pixel instead of being rounded
            # away on every tick. A no-motion frame must not create a click.
            self._last_logical_position = position
            self._model_position = position
            return
        try:
            if self._down:
                self._guard_cursor_origin()
            if (not self._point_is_safe(endpoint) or
                    (not self._roomy(endpoint) and
                     self._edge_distance(endpoint) < self._edge_distance(previous))):
                return self._continue_at_edge(position, logical)
            return self._send_motion(position, logical)
        except _CursorOriginChanged as changed:
            try:
                self._stage_origin_change(position, logical, changed.position)
            except Exception:
                self._interlock.mark_cancel('windows_unexpected_cursor_origin')
                self.emergency_release('windows_unexpected_cursor_origin')
                raise
        except Exception:
            self._interlock.mark_cancel('windows_motion_failed')
            self.emergency_release('windows_motion_failed')
            raise

    def _guard_cursor_origin(self):
        # This mandatory read is independent of optional diagnostics. Hook
        # confirmation acknowledges our event, not the host's current origin.
        actual = Vec2(*self._bindings.current_mouse_position())
        previous = self._pixel(self._last_event_position)
        if (actual - previous).length > 1.5:
            self._trace_control('windows_origin_mismatch', 'native_origin_changed', False,
                                from_position=previous, to_position=actual,
                                logical_position=self._last_logical_position,
                                details={'version': 'windows-origin.5',
                                         'recoverable': self._known_origin_change(actual),
                                         'originState': self._origin_diagnostic_details(actual, self._windows_pending)})
            self._trace_origin_sample('guard_mismatch', actual, self._windows_pending, force=True)
            raise _CursorOriginChanged(actual)

    def _origin_diagnostic_details(self, actual, pending):
        """Describe the exact decision sample, never replace it with a later read."""
        try:
            return self._build_origin_diagnostic_details(actual, pending)
        except Exception as exc:
            # In particular, formatting a failure must never prevent the
            # cancellation and emergency UP that follow it.
            return {'version': CAPTURE_TRACE_VERSION,
                    'diagnosticError': '%s: %s' % (type(exc).__name__, exc)}

    def _build_origin_diagnostic_details(self, actual, pending):
        now = self._clock()
        expected = self._pixel(self._last_event_position)
        candidates = [(f'recentDown[{i}]', point) for i, point in enumerate(self._windows_restore_points)]
        candidates.extend((('burstDown', self._windows_burst_origin),
                           ('releaseLogical', self._windows_release_origin)))
        return {
            'version': CAPTURE_TRACE_VERSION,
            'sampledAt': now,
            'actual': self._vec_dict(actual),
            'expected': self._vec_dict(expected),
            'distanceFromExpected': None if actual is None else (actual - expected).length,
            'phase': None if pending is None else pending.phase,
            'elapsedMs': None if pending is None else (now - pending.started_at) * 1000,
            'phaseElapsedMs': None if pending is None else (now - pending.phase_started_at) * 1000,
            'stableForMs': None if pending is None or pending.candidate is None else (now - pending.stable_since) * 1000,
            'candidate': self._vec_dict(None if pending is None else pending.candidate),
            'landing': self._vec_dict(None if pending is None else pending.landing),
            'logicalOrigin': self._vec_dict(self._last_logical_position if pending is None else pending.origin),
            'pendingLogical': self._vec_dict(None if pending is None else pending.position),
            'mappingLogicalAnchor': self._vec_dict(self._mapping_logical_anchor),
            'mappingEventAnchor': self._vec_dict(self._mapping_event_anchor),
            'restoreWindowRemainingMs': max(0.0, (self._windows_reanchor_until - now) * 1000),
            'restoreTolerancePx': RESTORE_POINT_TOLERANCE,
            'restoreCandidates': [dict(name=name, position=self._vec_dict(point),
                                       distance=None if actual is None else (actual - point).length)
                                  for name, point in candidates if point is not None],
            'pressSequence': self._windows_press_sequence,
            'logicalDown': self._down,
            'physicalDown': self._physical_down.is_set(),
            'captureGateVersion': CAPTURE_GATE_VERSION,
            'captureStatus': None if pending is None else pending.capture_status,
            'requestedDown': self._vec_dict(self._windows_press_landing),
            'confirmedDown': self._vec_dict(self._confirmed_press_position()),
            'downPostSequence': self._windows_press_post_sequence,
            'phaseTimeoutMs': RECOVERY_PHASE_TIMEOUT * 1000,
            'totalTimeoutMs': RECOVERY_TIMEOUT * 1000,
        }

    def _trace_origin_sample(self, reason, actual, pending, *, force=False):
        if not self._native_cursor_diagnostics or self._trace_callback is None:
            return
        # Stable polling is deduplicated; every changed position and phase is
        # retained. Native sampling is throttled independently below.
        try:
            key = (None if pending is None else pending.phase, actual,
                   None if pending is None else pending.candidate)
            changed = key != self._windows_origin_trace_key
            if force or changed:
                self._windows_origin_trace_key = key
                self._trace_control('windows_origin_sample', reason,
                                    reason not in ('stage_rejected', 'recovery_failed', 'guard_mismatch'),
                                    to_position=actual,
                                    details=self._origin_diagnostic_details(actual, pending))
            self._trace_capture_state(reason, force=force or changed)
        except Exception:
            # Diagnostics must never alter output, cancellation or recovery.
            pass

    def _trace_capture_state(self, reason, *, force=False):
        if not self._native_cursor_diagnostics or self._trace_callback is None:
            return
        try:
            now = self._clock()
            if not force and (now > self._windows_capture_until or now < self._windows_capture_next_sample):
                return
            self._windows_capture_next_sample = now + CURSOR_SETTLE
            reader = getattr(self._bindings, 'capture_diagnostics', None)
            if not callable(reader):
                return
            try:
                sample = reader(target_pid=getattr(self._source, 'target_pid', None))
            except Exception as exc:
                sample = {'errors': ['%s: %s' % (type(exc).__name__, exc)]}
            state = (sample.get('foreground'), sample.get('target'),
                     sample.get('asyncLeftDown'), sample.get('errors'))
            changed = state != self._windows_capture_last_state
            if force or changed or now - self._windows_capture_last_emit >= .05:
                self._windows_capture_last_state = state
                self._windows_capture_last_emit = now
                pending = self._windows_pending
                self._trace_control('windows_capture_state', reason, not bool(sample.get('errors')),
                                    logical_position=self._last_logical_position,
                                    details={'version': CAPTURE_TRACE_VERSION,
                                             'pressSequence': self._windows_press_sequence,
                                             'phase': None if pending is None else pending.phase,
                                             'physicalDown': self._physical_down.is_set(),
                                             'logicalDown': self._down,
                                             'stateChanged': changed,
                                             'sample': sample})
        except Exception:
            pass

    def _sample_native_cursor(self):
        """Read-only telemetry; failure must not become a motion failure."""
        sample = {'startedAt': self._clock()}
        try:
            sample['position'] = self._vec_dict(Vec2(*self._bindings.current_mouse_position()))
        except Exception as exc:
            sample['error'] = '%s: %s' % (type(exc).__name__, exc)
        sample['finishedAt'] = self._clock()
        return sample

    def _post_event(self, kind, position, reason, **kwargs):
        if kind in ('down', 'drag', 'move') and self._cancelled():
            return False
        diagnostic = self._native_cursor_diagnostics and self._trace_callback is not None
        if kind == 'down':
            self._windows_press_sequence += 1
        if kind in ('down', 'up'):
            self._windows_capture_until = self._clock() + RESTORE_WINDOW
        if diagnostic:
            self._trace_capture_state('before_' + kind, force=kind in ('down', 'up', 'move'))
        read_at = self._clock() if diagnostic else None
        if kind == "up":
            # Release where the pointer actually is, without relocating it.
            # Keep this original mandatory read and its failure semantics.
            position = Vec2(*self._bindings.current_mouse_position())
            before = {'startedAt': read_at, 'finishedAt': self._clock(),
                      'position': self._vec_dict(position)} if diagnostic else None
        else:
            position = self._pixel(position)
            before = self._sample_native_cursor() if diagnostic else None
        previous = self._vec_dict(self._last_event_position) if diagnostic else None
        posted = False
        error = ''
        native_started_at = self._clock()
        try:
            if kind == 'drag' or kwargs.get('stationary_down'):
                # Also covers a relocation during the first/repeated DOWN or
                # between the frame-entry check and the native post.
                self._guard_cursor_origin()
            if kind in ('down', 'drag', 'move') and self._cancelled():
                return False
            posted = super()._post_event(kind, position, reason, **kwargs)
        except Exception as exc:
            error = '%s: %s' % (type(exc).__name__, exc)
            raise
        finally:
            if diagnostic:
                # Immediate post-return is not Resolve acknowledgement. The
                # next pre-send sample reveals changes between native posts.
                after = self._sample_native_cursor()
                self._trace_control('windows_native_cursor_sample', reason, posted,
                                    logical_position=self._last_logical_position,
                                    error=error,
                                    details={'version': 'native-cursor.1', 'nativeKind': kind,
                                             'pressSequence': self._windows_press_sequence,
                                             'requestedPosition': self._vec_dict(position),
                                             'previousPlannedPosition': previous,
                                             'before': before, 'after': after})
                self._trace_capture_state('after_' + kind, force=kind in ('down', 'up', 'move'))
        if posted and kind == 'down':
            self._windows_press_landing = position
            self._windows_press_post_sequence = self._interlock.posted_sequence()
            record = self._interlock.native_down_record()
            if record is not None and record[1] >= native_started_at:
                point, timestamp = record
            else:
                # A hook callback may race this fallback read. Keep the post
                # admission time so its authoritative DOWN timestamp can still
                # replace the provisional cursor sample on the next check.
                point, timestamp = self._bindings.current_mouse_position(), native_started_at
            self._windows_down_point = Vec2(*point)
            self._windows_down_at = timestamp
            self._bindings._last_wheel_down = (tuple(point), timestamp)
        if posted and kind == 'up':
            self._windows_last_up_at = self._clock()
        return posted
