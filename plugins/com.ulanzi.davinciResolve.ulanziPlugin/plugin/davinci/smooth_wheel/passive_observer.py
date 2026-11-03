"""Latest-only visual observations of the Resolve wheel handle.

The observer itself never mutates the gesture engine. It captures a small
in-memory ROI on a private thread and reports predicted-versus-observed state;
an optional callback may commit a validated correction at an idle boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Condition, RLock, Thread, current_thread
import time
from typing import Any, Callable, Mapping, Optional, Tuple

from .macos import CapturedBitmap
from .transport_trace import TransportTrace


Point = Tuple[float, float]
SnapshotProvider = Callable[[], Any]
TraceCallback = Callable[[dict], None]
ResultCallback = Callable[[dict], None]
MAX_OBSERVER_ROI_SIDE = 256.0
MAX_OBSERVER_PIXEL_SIDE = 1024
MAX_OBSERVER_PIXEL_AREA = 1024 * 1024
VISUAL_CHECKPOINT_EVERY_DRAGS = 3
FRESH_RECOVERY_DELAY = 0.04
FRESH_RECOVERY_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class _ObservationRequest:
    revision: int
    requested_at: float
    due_at: float
    trigger: str
    gesture_id: int
    mode: str
    predicted: Point


def _point(value: Any) -> Optional[Point]:
    if value is None:
        return None
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
        point = (float(raw_x), float(raw_y))
    except (TypeError, ValueError):
        return None
    return point if all(math.isfinite(item) for item in point) else None


def _snapshot_handle(snapshot: Any) -> Optional[Point]:
    if snapshot is None:
        return None
    if isinstance(snapshot, Mapping):
        return _point(snapshot.get("handle") or snapshot.get("modelHandle"))
    return _point(getattr(snapshot, "handle", None))


def _snapshot_motion_revision(snapshot: Any) -> Optional[int]:
    if snapshot is None:
        return None
    raw = (
        snapshot.get("motionRevision", snapshot.get("motion_revision"))
        if isinstance(snapshot, Mapping)
        else getattr(snapshot, "motion_revision", None)
    )
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    return raw


def _snapshot_fresh_epoch(snapshot: Any) -> int:
    if snapshot is None:
        return 0
    raw = (
        snapshot.get("freshHandleEpoch", snapshot.get("fresh_handle_epoch", 0))
        if isinstance(snapshot, Mapping)
        else getattr(snapshot, "fresh_handle_epoch", 0)
    )
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return 0
    return raw


def _snapshot_active_mode(snapshot: Any) -> Optional[str]:
    if snapshot is None:
        return None
    raw = (
        snapshot.get("activeMode", snapshot.get("active_mode"))
        if isinstance(snapshot, Mapping)
        else getattr(snapshot, "active_mode", None)
    )
    normalized = str(getattr(raw, "value", raw) or "")
    return normalized if normalized in ("orbit", "push_pull") else None


def _snapshot_model_trace(snapshot: Any, predicted: Point) -> dict:
    """Serialize the already-read snapshot; never request another engine read."""

    def field(camel: str, snake: str) -> Any:
        if isinstance(snapshot, Mapping):
            return snapshot.get(camel, snapshot.get(snake))
        return getattr(snapshot, snake, None)

    def vector(camel: str, snake: str) -> Optional[dict]:
        value = _point(field(camel, snake))
        return {"x": value[0], "y": value[1]} if value is not None else None

    def number(camel: str, snake: str) -> Optional[float]:
        value = field(camel, snake)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value if math.isfinite(value) else None

    return {
        "handle": {"x": predicted[0], "y": predicted[1]},
        "diameterAxis": vector("diameterAxis", "diameter_axis"),
        "signedRadius": number("signedRadius", "signed_radius"),
        "lastNonzeroAxis": vector("lastNonzeroAxis", "last_nonzero_axis"),
        "diameterLastSide": number("diameterLastSide", "diameter_last_side"),
        "modelRevision": number("modelRevision", "model_revision"),
        "motionRevision": _snapshot_motion_revision(snapshot),
        "freshHandleEpoch": _snapshot_fresh_epoch(snapshot),
        "activeMode": _snapshot_active_mode(snapshot),
    }


def _pixel_screen_point(bitmap: CapturedBitmap, x: float, y: float) -> Point:
    left, top, _width, _height = bitmap.screen_rect
    return (
        left + x / bitmap.scale_x,
        top + y / bitmap.scale_y,
    )


def _integral_wheel_roi(roi: tuple) -> tuple:
    """Mirror capture_screen_region's existing integral global-point bounds."""
    x, y, width, height = roi
    left, top = math.floor(x), math.floor(y)
    return (left, top, math.ceil(x + width) - left, math.ceil(y + height) - top)


def _numeric_capture_roi(plan: Any, wheel_roi: tuple) -> tuple:
    capture_roi = tuple(float(value) for value in plan.capture_roi)
    if len(capture_roi) != 4 or not all(math.isfinite(value) for value in capture_roi):
        raise ValueError("numeric capture ROI must contain four finite values")
    original = _integral_wheel_roi(wheel_roi)
    if (
        capture_roi[:3] != original[:3]
        or capture_roi[3] < original[3]
        or not capture_roi[3].is_integer()
    ):
        raise ValueError("numeric capture may only extend the integral wheel ROI downward")
    return capture_roi


def _wheel_crop_shape(bitmap: CapturedBitmap, roi: tuple) -> tuple:
    original = _integral_wheel_roi(roi)
    left, top, width, height = original
    if (
        tuple(bitmap.screen_rect[:3]) != (left, top, width)
        or bitmap.screen_rect[3] < height
        or not math.isfinite(bitmap.scale_x)
        or not math.isfinite(bitmap.scale_y)
        or bitmap.scale_x <= 0.0
        or bitmap.scale_y <= 0.0
    ):
        raise ValueError("cannot prove the original wheel pixel mapping")
    pixel_width, pixel_height = width * bitmap.scale_x, height * bitmap.scale_y
    rounded_width, rounded_height = round(pixel_width), round(pixel_height)
    if (
        not math.isclose(pixel_width, rounded_width, rel_tol=0.0, abs_tol=1e-7)
        or not math.isclose(pixel_height, rounded_height, rel_tol=0.0, abs_tol=1e-7)
        or rounded_width <= 0 or rounded_height <= 0
        or rounded_width != bitmap.width or rounded_height > bitmap.height
        or bitmap.bytes_per_row < bitmap.width * 4
        or len(bitmap.pixels) < bitmap.bytes_per_row * bitmap.height
    ):
        raise ValueError("original wheel ROI does not align to complete captured pixels")
    return original, rounded_width, rounded_height


def _crop_original_wheel_bitmap(bitmap: CapturedBitmap, roi: tuple) -> CapturedBitmap:
    """Failure fallback: exact top-row prefix only, with no second capture."""
    original, width, height = _wheel_crop_shape(bitmap, roi)
    return CapturedBitmap(
        pixels=bitmap.pixels[:bitmap.bytes_per_row * height],
        width=width, height=height, bytes_per_row=bitmap.bytes_per_row,
        screen_rect=original, scale_x=bitmap.scale_x, scale_y=bitmap.scale_y,
        color_offsets=bitmap.color_offsets,
    )


def _validate_wheel_crop(cropped: CapturedBitmap, full: CapturedBitmap, roi: tuple) -> None:
    original, width, height = _wheel_crop_shape(full, roi)
    if (
        tuple(cropped.screen_rect) != original
        or cropped.width != width or cropped.height != height
        or cropped.scale_x != full.scale_x or cropped.scale_y != full.scale_y
        or cropped.bytes_per_row != full.bytes_per_row
        or cropped.color_offsets != full.color_offsets
        or len(cropped.pixels) < cropped.bytes_per_row * height
    ):
        raise ValueError("numeric crop changed the original wheel bitmap mapping")


def detect_neutral_handle(
    bitmap: CapturedBitmap,
    center: Point,
    max_radius: float,
    expected_handle: Optional[Point] = None,
    *,
    should_abort: Optional[Callable[[], bool]] = None,
) -> Optional[dict]:
    """Find a compact gray/white component inside a calibrated wheel ROI.

    Resolve's handle is substantially dimmer than Jianying's.  The thresholds
    here come from the lab's successful screenshot experiments.  Classification
    uses channel minimum/spread, so the common RGBA/BGRA channel-order difference
    does not affect this neutral-color detector.
    """

    if (
        bitmap.width <= 0
        or bitmap.height <= 0
        or bitmap.width > MAX_OBSERVER_PIXEL_SIDE
        or bitmap.height > MAX_OBSERVER_PIXEL_SIDE
        or bitmap.width * bitmap.height > MAX_OBSERVER_PIXEL_AREA
        or bitmap.bytes_per_row < bitmap.width * 4
        or len(bitmap.pixels) < bitmap.bytes_per_row * bitmap.height
        or bitmap.scale_x <= 0.0
        or bitmap.scale_y <= 0.0
    ):
        return None
    center = _point(center)
    expected_handle = _point(expected_handle)
    try:
        max_radius = float(max_radius)
    except (TypeError, ValueError):
        return None
    if center is None or not math.isfinite(max_radius) or max_radius < 4.0:
        return None

    left, top, _logical_width, _logical_height = bitmap.screen_rect
    try:
        color_offsets = tuple(int(value) for value in bitmap.color_offsets)
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        len(color_offsets) != 3
        or len(set(color_offsets)) != 3
        or any(value < 0 or value > 3 for value in color_offsets)
    ):
        return None
    search_radius = max_radius + 2.0
    search_radius_squared = search_radius * search_radius
    pixel_count = bitmap.width * bitmap.height
    candidate_mask = bytearray(pixel_count)
    brightness = bytearray(pixel_count)
    pixels = bitmap.pixels
    for pixel_y in range(bitmap.height):
        if should_abort is not None and should_abort():
            return None
        screen_y = top + (pixel_y + 0.5) / bitmap.scale_y
        delta_y_squared = (screen_y - center[1]) ** 2
        row_offset = pixel_y * bitmap.bytes_per_row
        mask_row = pixel_y * bitmap.width
        for pixel_x in range(bitmap.width):
            screen_x = left + (pixel_x + 0.5) / bitmap.scale_x
            if (screen_x - center[0]) ** 2 + delta_y_squared > search_radius_squared:
                continue
            offset = row_offset + pixel_x * 4
            red, green, blue = (
                pixels[offset + color_offsets[0]],
                pixels[offset + color_offsets[1]],
                pixels[offset + color_offsets[2]],
            )
            minimum = min(red, green, blue)
            maximum = max(red, green, blue)
            if minimum < 120 or maximum - minimum > 35:
                continue
            index = mask_row + pixel_x
            candidate_mask[index] = 1
            brightness[index] = (red + green + blue) // 3

    expected_radius = (
        math.hypot(expected_handle[0] - center[0], expected_handle[1] - center[1])
        if expected_handle is not None
        else None
    )
    area_scale = max(1.0, bitmap.scale_x * bitmap.scale_y)
    scored = []
    for seed in range(pixel_count):
        if should_abort is not None and seed % 256 == 0 and should_abort():
            return None
        if not candidate_mask[seed]:
            continue
        candidate_mask[seed] = 0
        pending = [seed]
        count = 0
        min_x = bitmap.width
        max_x = -1
        min_y = bitmap.height
        max_y = -1
        total_brightness = 0.0
        weighted_x = 0.0
        weighted_y = 0.0
        while pending:
            if should_abort is not None and count % 256 == 0 and should_abort():
                return None
            index = pending.pop()
            pixel_y, pixel_x = divmod(index, bitmap.width)
            value = brightness[index]
            count += 1
            min_x = min(min_x, pixel_x)
            max_x = max(max_x, pixel_x)
            min_y = min(min_y, pixel_y)
            max_y = max(max_y, pixel_y)
            total_brightness += value
            weighted_x += (pixel_x + 0.5) * value
            weighted_y += (pixel_y + 0.5) * value
            for neighbour_y in range(
                max(0, pixel_y - 1), min(bitmap.height, pixel_y + 2)
            ):
                neighbour_row = neighbour_y * bitmap.width
                for neighbour_x in range(
                    max(0, pixel_x - 1), min(bitmap.width, pixel_x + 2)
                ):
                    neighbour = neighbour_row + neighbour_x
                    if candidate_mask[neighbour]:
                        candidate_mask[neighbour] = 0
                        pending.append(neighbour)
        if count < max(5, int(round(4.0 * area_scale))):
            continue
        if count > int(math.ceil(120.0 * area_scale)):
            continue
        pixel_width = max_x - min_x + 1
        pixel_height = max_y - min_y + 1
        logical_width = pixel_width / bitmap.scale_x
        logical_height = pixel_height / bitmap.scale_y
        if (
            logical_width < 2.0
            or logical_height < 2.0
            or logical_width > 18.0
            or logical_height > 18.0
        ):
            continue
        aspect = min(logical_width, logical_height) / max(logical_width, logical_height)
        fill = count / max(1, pixel_width * pixel_height)
        if aspect < 0.30 or fill < 0.32:
            continue
        if total_brightness <= 0.0:
            continue
        centroid_pixel_x = weighted_x / total_brightness
        centroid_pixel_y = weighted_y / total_brightness
        position = _pixel_screen_point(
            bitmap, centroid_pixel_x, centroid_pixel_y
        )
        radius = math.hypot(position[0] - center[0], position[1] - center[1])
        if radius > search_radius:
            continue
        # Reject the crosshair when the model confidently expects an off-centre
        # handle.  A true neutral handle is still allowed when the model is near
        # the centre, where the two visuals can merge.
        center_exclusion = max(5.0, max_radius * 0.11)
        if (
            expected_radius is not None
            and expected_radius > center_exclusion * 1.5
            and radius < center_exclusion
        ):
            continue
        expected_distance = (
            math.hypot(
                position[0] - expected_handle[0], position[1] - expected_handle[1]
            )
            if expected_handle is not None
            else 0.0
        )
        clipped_rim = aspect < 0.48
        if clipped_rim and not (
            expected_radius is not None and expected_radius >= .90 * max_radius
            and radius >= .90 * max_radius and expected_distance <= 3.0
            and max(logical_width, logical_height) <= 7.0
        ):
            continue
        mean_brightness = total_brightness / count
        score = (
            min(count / area_scale, 30.0) * 5.0
            + mean_brightness
            + fill * 35.0
            + aspect * 20.0
            - expected_distance * 1.25
            - abs(logical_width - logical_height) * 4.0
        )
        scored.append({
            "clippedRim": clipped_rim,
            "score": score,
            "position": position,
            "radius": radius,
            "pixelCount": count,
            "meanBrightness": mean_brightness,
            "fillRatio": fill,
            "aspectRatio": aspect,
            "expectedDistance": expected_distance,
            "bbox": {
                "left": left + min_x / bitmap.scale_x,
                "top": top + min_y / bitmap.scale_y,
                "width": logical_width,
                "height": logical_height,
            },
        })

    if not scored:
        return None
    scored.sort(key=lambda item: item["score"], reverse=True)
    best = scored[0]
    if best["clippedRim"] and len(scored) != 1:
        return None
    runner_up_margin = (
        best["score"] - scored[1]["score"] if len(scored) > 1 else 60.0
    )
    confidence = 0.25
    confidence += min(0.25, best["fillRatio"] * 0.25)
    confidence += min(0.20, best["aspectRatio"] * 0.20)
    confidence += min(0.20, max(0.0, runner_up_margin) / 150.0)
    confidence += min(0.10, max(0.0, best["meanBrightness"] - 120.0) / 1350.0)
    confidence -= min(0.25, best["expectedDistance"] / max(1.0, max_radius) * 0.20)
    position = best["position"]
    return {
        "clippedRim": best["clippedRim"],
        "position": {"x": position[0], "y": position[1]},
        "radius": best["radius"],
        "angleDeg": math.degrees(
            math.atan2(position[1] - center[1], position[0] - center[0])
        ) % 360.0,
        "pixelCount": best["pixelCount"],
        "meanBrightness": best["meanBrightness"],
        "bbox": best["bbox"],
        "confidence": max(0.0, min(1.0, confidence)),
        "candidateCount": len(scored),
    }


class PassiveWheelObserver:
    """One sparse, latest-only sampler with a replaceable pending request."""

    def __init__(
        self,
        bindings: Any,
        center: Any,
        max_radius: float,
        session_id: Any,
        generation: Any,
        snapshot_provider: SnapshotProvider,
        trace_callback: TraceCallback,
        result_callback: Optional[ResultCallback] = None,
        clock: Callable[[], float] = time.monotonic,
        quiet_delay: float = 0.18,
        numeric_capture: Any = None,
        display_bounds: Any = None,
        idle_only: bool = False,
    ) -> None:
        parsed_center = _point(center)
        try:
            parsed_radius = float(max_radius)
            parsed_delay = float(quiet_delay)
        except (TypeError, ValueError) as exc:
            raise ValueError("observer radius and quiet delay must be numeric") from exc
        if parsed_center is None:
            raise ValueError("observer center must contain two finite values")
        if not math.isfinite(parsed_radius) or parsed_radius < 4.0:
            raise ValueError("observer max_radius must be finite and at least four")
        margin = max(6.0, parsed_radius * 0.12)
        if (parsed_radius + margin) * 2.0 > MAX_OBSERVER_ROI_SIDE:
            raise ValueError("observer wheel ROI exceeds the passive safety limit")
        if not math.isfinite(parsed_delay) or parsed_delay < 0.0:
            raise ValueError("observer quiet_delay must be finite and non-negative")
        if not callable(snapshot_provider) or not callable(trace_callback):
            raise TypeError("snapshot_provider and trace_callback must be callable")
        if result_callback is not None and not callable(result_callback):
            raise TypeError("result_callback must be callable when provided")

        self._bindings = bindings
        self._idle_only = bool(idle_only)
        self._center = parsed_center
        self._max_radius = parsed_radius
        self._session_id = session_id
        self._generation = generation
        self._snapshot_provider = snapshot_provider
        self._trace_callback = trace_callback
        self._result_callback = result_callback
        self._observer_only = result_callback is None
        self._clock = clock
        self._quiet_delay = parsed_delay
        self._numeric_capture = numeric_capture
        self._numeric_display_bounds = display_bounds
        self._numeric_sample_sequence = 0
        self._condition = Condition(RLock())
        self._thread: Optional[Thread] = None
        self._started = False
        self._closed = False
        self._revision = 0
        self._gesture_id = 0
        self._pointer_down = False
        self._drag_frames = 0
        self._pending: Optional[_ObservationRequest] = None
        self._inflight_revision: Optional[int] = None
        self._fresh_recovery_revision: Optional[int] = None
        self._fresh_recovery_attempt = 0
        self._fresh_recovery_retry_mode: Optional[str] = None
        self._deferred_gesture_end: Optional[Tuple[str, int, Point]] = None
        self._zero_clamp_recovery_latched = False
        self._predicted = parsed_center
        self._last_mode = "initial"
        self._observations = 0
        self._failures = 0
        self._discarded = 0
        self._last_error = ""
        self._last_result: Optional[dict] = None
        self._close_timed_out = False
        self._callback_failures = 0
        self._callback_inflight_revision: Optional[int] = None
        self._rim_confirmation = None
        self._next_input_recovery_at = 0.0
        self._transport_trace = TransportTrace()

    def start(self, initial_handle: Any) -> None:
        handle = _point(initial_handle)
        if handle is None:
            raise ValueError("initial_handle must contain two finite values")
        with self._condition:
            if self._closed:
                raise RuntimeError("passive observer is closed")
            if self._started:
                return
            self._started = True
            self._predicted = handle
            self._schedule_locked("initial", "arm_baseline")
            self._thread = Thread(
                target=self._run,
                name="wheel-passive-observer-%s" % self._session_id,
                daemon=True,
            )
            self._thread.start()

    def note_input(self, mode: Any, *, fresh_required: bool = False) -> None:
        """Replace the pending observation and restart the quiet window."""

        normalized = str(getattr(mode, "value", mode) or "unknown")
        with self._condition:
            if not self._started or self._closed:
                return
            self._last_mode = normalized
            if fresh_required:
                # Failed capture batches must not strand a paused queue behind
                # a quiet window that every new encoder event postpones.
                now = self._clock()
                if now >= self._next_input_recovery_at:
                    self._next_input_recovery_at = now + .250
                    self._request_fresh_recovery_locked(normalized)
                return
            self._next_input_recovery_at = 0.0
            # Input callbacks can be much denser than rendered pointer frames.
            # During a held gesture the rendered DRAG cadence below owns visual
            # scheduling, so encoder callbacks never create screenshot pressure.
            if not self._pointer_down:
                self._schedule_locked(normalized, "input_settled")

    def request_fresh_recovery(
        self,
        mode: Any,
        *,
        force_next: bool = False,
    ) -> bool:
        """Schedule one prompt recovery sample that normal input cannot replace.

        A hard visual barrier may be established while the engine is already
        idle (for example, an outward radial step at the exact rim).  Waiting
        for the ordinary input quiet window would let a continuous encoder
        stream postpone recovery forever.  This dedicated slot remains owned
        until its capture and optional feedback callback have both finished.
        """

        normalized = str(getattr(mode, "value", mode) or self._last_mode)
        with self._condition:
            if not self._started or self._closed:
                return False
            self._last_mode = normalized
            return self._request_fresh_recovery_locked(
                normalized,
                force_next=force_next,
            )

    def note_pointer(self, event: Any) -> None:
        """Track successful logical DRAG frames without affecting their sink."""

        if not isinstance(event, Mapping):
            return
        try:
            self._transport_trace.record(event, self._clock())
        except Exception:
            pass  # Diagnostics cannot affect the owner runner.
        kind = str(event.get("kind") or "")
        if event.get("ok") is False:
            return
        logical = event.get("logical")
        predicted = None
        mode = self._last_mode
        if isinstance(logical, Mapping):
            predicted = _point(logical.get("after"))
            mode = str(logical.get("mode") or mode)
        with self._condition:
            if not self._started or self._closed:
                return
            if kind == "down":
                self._gesture_id += 1
                self._pointer_down = True
                self._drag_frames = 0
                self._zero_clamp_recovery_latched = False
                self._schedule_locked(mode, "gesture_start", delay=0.04)
                return
            if predicted is not None:
                self._predicted = predicted
            self._last_mode = mode
            if kind == "drag":
                self._zero_clamp_recovery_latched = False
                self._drag_frames += 1
                if self._drag_frames % VISUAL_CHECKPOINT_EVERY_DRAGS == 0:
                    # Capture on the private observer thread. Any later DRAG
                    # increments the revision and makes the result disposable;
                    # the 120 Hz motion loop never waits for it.
                    self._schedule_locked(mode, "motion_checkpoint", delay=0.0)
                else:
                    self._schedule_locked(mode, "motion_settled")
            elif kind == "up":
                self._pointer_down = False
                # Resolve can change or reset a control when a drag is released.
                # Sample shortly after UP so the passive log can distinguish
                # movement during the drag from a release-time reset.
                self._schedule_locked(mode, "gesture_end", delay=0.04)
            elif (
                kind == "motion_observed"
                and isinstance(logical, Mapping)
                and bool(logical.get("clamped"))
                and not self._zero_clamp_recovery_latched
            ):
                # An exact-rim no-op has no DOWN/UP lifecycle, so it cannot
                # rely on a terminal sample. Promote the first clamp in this
                # stationary boundary run directly into the protected slot.
                self._zero_clamp_recovery_latched = True
                self._request_fresh_recovery_locked(mode)

    def close(self, reason: str = "observer_close") -> bool:
        skipped_end = None
        with self._condition:
            if self._closed:
                thread = self._thread
            else:
                self._closed = True
                if (
                    self._pending is not None
                    and self._pending.trigger == "gesture_end"
                ):
                    skipped_end = self._pending
                    self._discarded += 1
                self._pending = None
                self._fresh_recovery_revision = None
                self._fresh_recovery_attempt = 0
                self._fresh_recovery_retry_mode = None
                self._deferred_gesture_end = None
                self._condition.notify_all()
                thread = self._thread
        if skipped_end is not None:
            self._trace({
                "kind": "passive_observer",
                "phase": "discarded",
                "result": "discarded",
                "reason": "observer_closed_before_gesture_end",
                "closeReason": str(reason or "observer_close"),
                "sessionId": self._session_id,
                "generation": self._generation,
                "revision": skipped_end.revision,
                "gestureId": skipped_end.gesture_id,
                "trigger": skipped_end.trigger,
                "observerOnly": self._observer_only,
            })
        if thread is not None and thread is not current_thread():
            thread.join(0.10)
        stopped = thread is None or not thread.is_alive()
        if not stopped:
            with self._condition:
                self._close_timed_out = True
        return stopped

    def status(self) -> dict:
        with self._condition:
            thread = self._thread
            return {
                "mode": "passive",
                "idleOnly": self._idle_only,
                "observerOnly": self._observer_only,
                "started": self._started,
                "closed": self._closed,
                "alive": bool(thread is not None and thread.is_alive()),
                "pending": self._pending is not None,
                "inFlight": self._inflight_revision is not None,
                "freshRecoveryPending": self._fresh_recovery_revision is not None,
                "freshRecoveryRevision": self._fresh_recovery_revision,
                "freshRecoveryAttempt": self._fresh_recovery_attempt,
                "freshRecoveryMaxAttempts": FRESH_RECOVERY_MAX_ATTEMPTS,
                "freshRecoveryRetry": self._fresh_recovery_retry_mode is not None,
                "deferredGestureEnd": self._deferred_gesture_end is not None,
                "zeroClampRecoveryLatched": self._zero_clamp_recovery_latched,
                "revision": self._revision,
                "gestureId": self._gesture_id,
                "pointerDown": self._pointer_down,
                "dragFrames": self._drag_frames,
                "checkpointEveryDrags": VISUAL_CHECKPOINT_EVERY_DRAGS,
                "observations": self._observations,
                "failures": self._failures,
                "discarded": self._discarded,
                "lastError": self._last_error,
                "lastResult": dict(self._last_result) if self._last_result else None,
                "closeTimedOut": self._close_timed_out,
                "callbackFailures": self._callback_failures,
                "callbackInFlight": self._callback_inflight_revision is not None,
                "callbackRevision": self._callback_inflight_revision,
                "quietDelayMs": self._quiet_delay * 1000.0,
                "sessionId": self._session_id,
                "generation": self._generation,
            }

    def _schedule_locked(
        self,
        mode: str,
        trigger: str,
        delay: Optional[float] = None,
        *,
        gesture_id: Optional[int] = None,
        predicted: Optional[Point] = None,
    ) -> None:
        if self._idle_only:
            # Every new input/frame invalidates old work, including a terminal
            # sample that has already begun. Only a quiet input or UP may scan.
            self._revision += 1
            self._pending = None
            if self._pointer_down or trigger not in ("input_settled", "gesture_end"):
                return
            delay = self._quiet_delay
        if (
            self._fresh_recovery_revision is not None
            and trigger != "fresh_recovery"
        ):
            # Preserve both pending and in-flight recovery work.  In
            # particular, dense note_input calls cannot keep pushing this
            # capture behind the normal quiet window.
            if trigger == "gesture_end":
                # A fresh capture may have started just before the owner
                # runner posts UP. Preserve that terminal edge and schedule it
                # as soon as the protected capture/callback leaves the slot.
                self._deferred_gesture_end = (
                    mode,
                    self._gesture_id,
                    self._predicted,
                )
            return
        if (
            self._pending is not None
            and self._pending.trigger == "gesture_end"
            and trigger not in ("gesture_end", "fresh_recovery")
        ):
            # Preserve the short terminal sample. A new physical DOWN is held
            # back by the click guard, and its later DRAG will schedule a fresh
            # observation after this release edge has been recorded.
            return
        self._revision += 1
        requested_at = self._clock()
        effective_delay = self._quiet_delay if delay is None else max(0.0, float(delay))
        self._pending = _ObservationRequest(
            revision=self._revision,
            requested_at=requested_at,
            due_at=requested_at + effective_delay,
            trigger=trigger,
            gesture_id=(self._gesture_id if gesture_id is None else gesture_id),
            mode=mode,
            predicted=(self._predicted if predicted is None else predicted),
        )
        self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                request = self._next_request_locked()
                if request is None:
                    return
                self._pending = None
                self._inflight_revision = request.revision
            result = self._observe(request)
            stale = False
            with self._condition:
                self._inflight_revision = None
                if self._closed:
                    return
                stale = request.revision != self._revision
                if stale:
                    self._discarded += 1
                else:
                    self._last_result = result
                    if result.get("result") == "ready":
                        self._observations += 1
                        self._last_error = ""
                    else:
                        self._failures += 1
                        self._last_error = str(result.get("reason") or "unknown")
            if stale:
                self._trace({
                    # Keep the raw, already-captured evidence, but never feed a
                    # superseded sample back into the gesture engine.
                    **result,
                    "kind": "passive_observer",
                    "phase": "discarded",
                    "result": "discarded",
                    "reason": "stale_revision",
                    "observedResult": result.get("result"),
                    "observedReason": result.get("reason"),
                    "sessionId": self._session_id,
                    "generation": self._generation,
                    "revision": request.revision,
                    "gestureId": request.gesture_id,
                    "trigger": request.trigger,
                    "observerOnly": self._observer_only,
                })
            else:
                self._trace(result)
                if result.get("result") == "ready" and self._result_callback is not None:
                    # Trace delivery is deliberately outside the condition and may
                    # race with close() or a newer motion revision. Admit the
                    # feedback callback only after a final, short locked check.
                    # close() therefore prevents every new admission while an
                    # already-admitted callback remains bounded by its 100 ms join.
                    callback_admitted = False
                    with self._condition:
                        if (
                            not self._closed
                            and request.revision == self._revision
                        ):
                            self._callback_inflight_revision = request.revision
                            callback_admitted = True
                    if callback_admitted:
                        try:
                            self._result_callback(dict(result))
                        except Exception as exc:
                            with self._condition:
                                self._callback_failures += 1
                                self._last_error = "feedback_callback_failed:%s" % exc
                            self._trace({
                                "kind": "passive_observer",
                                "phase": "feedback_callback",
                                "result": "failed",
                                "reason": "feedback_callback_failed",
                                "detail": str(exc),
                                "sessionId": self._session_id,
                                "generation": self._generation,
                                "revision": request.revision,
                                "gestureId": request.gesture_id,
                                "trigger": request.trigger,
                                "observerOnly": False,
                            })
                        finally:
                            with self._condition:
                                if self._callback_inflight_revision == request.revision:
                                    self._callback_inflight_revision = None
                                self._condition.notify_all()
            with self._condition:
                if self._fresh_recovery_revision == request.revision:
                    self._fresh_recovery_revision = None
                    completed_attempt = self._fresh_recovery_attempt
                    deferred_end = self._deferred_gesture_end
                    self._deferred_gesture_end = None
                    retry_mode = self._fresh_recovery_retry_mode
                    self._fresh_recovery_retry_mode = None
                    if (
                        result.get("result") != "ready"
                        and completed_attempt < FRESH_RECOVERY_MAX_ATTEMPTS
                    ):
                        retry_mode = retry_mode or request.mode
                    if deferred_end is not None and not self._closed:
                        self._fresh_recovery_attempt = 0
                        mode, gesture_id, predicted = deferred_end
                        self._schedule_locked(
                            mode,
                            "gesture_end",
                            delay=FRESH_RECOVERY_DELAY,
                            gesture_id=gesture_id,
                            predicted=predicted,
                        )
                    elif retry_mode is not None and not self._closed:
                        self._schedule_fresh_recovery_locked(
                            retry_mode,
                            attempt=completed_attempt + 1,
                        )
                    else:
                        self._fresh_recovery_attempt = 0
                self._condition.notify_all()

    def _request_fresh_recovery_locked(
        self,
        mode: str,
        *,
        force_next: bool = False,
    ) -> bool:
        if self._idle_only:
            return False
        if self._fresh_recovery_revision is not None:
            if (
                force_next
                and self._fresh_recovery_attempt < FRESH_RECOVERY_MAX_ATTEMPTS
            ):
                self._fresh_recovery_retry_mode = mode
            return True
        return self._schedule_fresh_recovery_locked(mode, attempt=1)

    def _schedule_fresh_recovery_locked(self, mode: str, *, attempt: int) -> bool:
        pending = self._pending
        if pending is not None and pending.trigger == "gesture_end":
            # A prompt recovery is a stronger immediate request, but the
            # already-observed UP edge still deserves its post-release sample
            # if the prompt capture cannot settle the barrier.
            self._deferred_gesture_end = (
                pending.mode,
                pending.gesture_id,
                pending.predicted,
            )
        self._schedule_locked(
            mode,
            "fresh_recovery",
            delay=FRESH_RECOVERY_DELAY,
        )
        if self._pending is None or self._pending.trigger != "fresh_recovery":
            return False
        self._fresh_recovery_revision = self._pending.revision
        self._fresh_recovery_attempt = max(1, int(attempt))
        return True

    def _next_request_locked(self) -> Optional[_ObservationRequest]:
        while not self._closed:
            request = self._pending
            if request is None:
                self._condition.wait()
                continue
            remaining = request.due_at - self._clock()
            if remaining > 0.0:
                self._condition.wait(remaining)
                continue
            return request
        return None

    def _confirm_rim_handle(self, detected, request, epoch, at):
        if detected is None or not detected.get("clippedRim"):
            self._rim_confirmation = None
            return detected
        position = _point(detected["position"])
        previous = self._rim_confirmation
        self._rim_confirmation = (request.revision, request.gesture_id, epoch, at, position)
        if previous is not None:
            revision, gesture, old_epoch, old_at, old_position = previous
            if (request.revision > revision and request.gesture_id == gesture
                    and epoch == old_epoch and .020 <= at - old_at <= .500
                    and math.hypot(position[0] - old_position[0],
                                   position[1] - old_position[1]) <= 1.5):
                return {**detected, "rimConfirmationCount": 2}
        return None

    def _observe(self, request: _ObservationRequest) -> dict:
        started_at = self._clock()
        diagnostics = {
            "wheelCenter": {"x": self._center[0], "y": self._center[1]},
            "visualMaxRadius": self._max_radius,
            "timing": {
                "clock": "monotonic",
                "requestedAt": request.requested_at,
                "dueAt": request.due_at,
                "observationStartedAt": started_at,
            },
        }
        predicted = request.predicted
        motion_revision = None
        fresh_handle_epoch = 0
        observed_mode = request.mode
        try:
            snapshot = self._snapshot_provider()
            snapshot_handle = _snapshot_handle(snapshot)
            motion_revision = _snapshot_motion_revision(snapshot)
            fresh_handle_epoch = _snapshot_fresh_epoch(snapshot)
            observed_mode = _snapshot_active_mode(snapshot) or observed_mode
            if snapshot_handle is not None:
                predicted = snapshot_handle
        except Exception as exc:
            return self._failure(
                request, "snapshot_failed", started_at, str(exc), diagnostics=diagnostics
            )
        diagnostics["modelBeforeCapture"] = _snapshot_model_trace(snapshot, predicted)
        if self._idle_only and (
            self._idle_scan_superseded(request)
            or getattr(snapshot, "session_active", False)
            or abs(getattr(snapshot, "pending_angle", 0.0)) > 1e-9
            or abs(getattr(snapshot, "pending_radial", 0.0)) > 1e-9
        ):
            return self._failure(request, "motion_active", started_at, diagnostics=diagnostics)

        try:
            app = self._bindings.frontmost_app()
            if not getattr(app, "is_davinci", False):
                return self._failure(
                    request, "davinci_not_frontmost", started_at, diagnostics=diagnostics
                )
        except Exception as exc:
            return self._failure(
                request, "frontmost_check_failed", started_at, str(exc), diagnostics=diagnostics
            )
        try:
            if not self._bindings.screen_capture_allowed():
                return self._failure(
                    request, "screen_capture_permission_unavailable", started_at,
                    diagnostics=diagnostics,
                )
        except Exception as exc:
            return self._failure(
                request, "screen_capture_permission_check_failed", started_at, str(exc),
                diagnostics=diagnostics,
            )

        margin = max(6.0, self._max_radius * 0.12)
        half_size = self._max_radius + margin
        roi = (
            self._center[0] - half_size,
            self._center[1] - half_size,
            half_size * 2.0,
            half_size * 2.0,
        )
        capture_roi = roi
        numeric_plan = None
        if self._numeric_capture is not None:
            self._numeric_sample_sequence += 1
            diagnostics["numericCapture"] = {
                "captureId": "%s:%s:%s:%s" % (
                    self._session_id, self._generation, request.revision,
                    self._numeric_sample_sequence,
                ),
                "status": "unavailable",
                "reason": "plan_unavailable",
            }
            try:
                candidate = self._numeric_capture.prepare(roi, self._numeric_display_bounds)
                if candidate is not None:
                    capture_roi = _numeric_capture_roi(candidate, roi)
                    numeric_plan = candidate
                    diagnostics["numericCapture"].update(status="planned", reason="")
            except Exception as exc:
                diagnostics["numericCapture"].update(
                    status="failed", reason="prepare_failed", detail=str(exc),
                )
        capture_started = self._clock()
        diagnostics["timing"]["captureStartedAt"] = capture_started
        if self._idle_only and self._idle_scan_superseded(request):
            return self._failure(request, "motion_resumed", started_at, diagnostics=diagnostics)
        try:
            bitmap = self._bindings.capture_screen_region(*capture_roi)
        except Exception as exc:
            return self._failure(
                request, "screen_capture_failed", started_at, str(exc), diagnostics=diagnostics
            )
        capture_finished = self._clock()
        if self._idle_only and self._idle_scan_superseded(request):
            return self._failure(request, "motion_resumed", started_at, diagnostics=diagnostics)
        diagnostics["timing"]["captureFinishedAt"] = capture_finished
        try:
            diagnostics["transportWindow"] = self._transport_trace.capture_window(
                capture_started, capture_finished)
        except Exception:
            diagnostics["transportTraceError"] = "window_failed"
        detection_started = capture_finished
        full_bitmap = bitmap
        if numeric_plan is not None:
            try:
                bitmap = numeric_plan.crop_wheel(full_bitmap)
                _validate_wheel_crop(bitmap, full_bitmap, roi)
            except Exception as exc:
                diagnostics["numericCapture"].update(cropError=str(exc))
                try:
                    bitmap = _crop_original_wheel_bitmap(full_bitmap, roi)
                    diagnostics["numericCapture"]["cropFallback"] = True
                except Exception as crop_exc:
                    diagnostics["numericCapture"].update(
                        cropFallback=False, cropFallbackError=str(crop_exc),
                    )
                    failure = self._failure(
                        request, "numeric_capture_wheel_crop_failed", started_at,
                        str(crop_exc), diagnostics=diagnostics,
                    )
                    self._submit_numeric_capture(
                        numeric_plan, full_bitmap, request, failure,
                        observed_mode, motion_revision, result="failed",
                        reason="numeric_capture_wheel_crop_failed",
                    )
                    return failure
        try:
            detection_options = (
                {"should_abort": lambda: self._idle_scan_superseded(request)}
                if self._idle_only else {}
            )
            detected = detect_neutral_handle(
                bitmap, self._center, self._max_radius, predicted, **detection_options
            )
        except Exception as exc:
            failure = self._failure(
                request, "handle_detection_failed", started_at, str(exc), diagnostics=diagnostics
            )
            self._submit_numeric_capture(
                numeric_plan, full_bitmap, request, failure,
                observed_mode, motion_revision, result="failed", reason="handle_detection_failed",
            )
            return failure
        detection_finished = self._clock()
        diagnostics["timing"]["detectionFinishedAt"] = detection_finished
        diagnostics["timing"]["observationFinishedAt"] = detection_finished
        raw_detected = detected
        if raw_detected is not None:
            try:
                diagnostics["transportMeasurement"] = self._transport_trace.measurement(
                    raw_detected["position"], {"x": predicted[0], "y": predicted[1]},
                    {"x": self._center[0], "y": self._center[1]}, capture_started,
                    capture_finished, request.revision, request.gesture_id)
            except Exception:
                diagnostics["transportTraceError"] = "measurement_failed"
        detected = self._confirm_rim_handle(detected, request, fresh_handle_epoch, detection_finished)
        detection_reason = (
            "observed" if detected is not None else "rim_handle_needs_confirmation"
            if raw_detected is not None else "white_handle_not_detected"
        )
        self._submit_numeric_capture(
            numeric_plan, full_bitmap, request, diagnostics, observed_mode, motion_revision,
            result="ready" if detected is not None else "failed",
            reason=detection_reason,
            actual=detected.get("position") if detected is not None else None,
            handle_detection=detected,
        )
        if detected is None:
            return self._failure(
                request, detection_reason, started_at, diagnostics=diagnostics
            )
        actual = detected["position"]
        drift = math.hypot(actual["x"] - predicted[0], actual["y"] - predicted[1])
        return {
            **diagnostics,
            "kind": "passive_observer",
            "phase": "sample",
            "result": "ready",
            "reason": "observed",
            "sessionId": self._session_id,
            "generation": self._generation,
            "revision": request.revision,
            "gestureId": request.gesture_id,
            "trigger": request.trigger,
            "mode": observed_mode,
            "motionRevision": motion_revision,
            "freshHandleEpoch": fresh_handle_epoch,
            "predicted": {"x": predicted[0], "y": predicted[1]},
            "actual": actual,
            "driftPx": drift,
            "handle": detected,
            "roi": {"x": roi[0], "y": roi[1], "w": roi[2], "h": roi[3]},
            "captureScale": {"x": bitmap.scale_x, "y": bitmap.scale_y},
            "captureMs": max(0.0, (capture_finished - capture_started) * 1000.0),
            "detectMs": max(0.0, (detection_finished - detection_started) * 1000.0),
            "totalMs": max(0.0, (detection_finished - started_at) * 1000.0),
            "observerOnly": self._observer_only,
        }

    def _idle_scan_superseded(self, request):
        # Read-only cancellation check, also used between pixel scan chunks.
        # Do not take engine/sink locks from inside the detector.
        return self._closed or self._pointer_down or request.revision != self._revision

    def _submit_numeric_capture(
        self, plan: Any, bitmap: CapturedBitmap, request: _ObservationRequest,
        diagnostics: dict, mode: str, motion_revision: Optional[int], *,
        result: str, reason: str, actual: Optional[dict] = None,
        handle_detection: Optional[dict] = None,
    ) -> None:
        """Transfer immutable pixels to a bounded diagnostic queue, never OCR/I/O."""
        if plan is None:
            return
        numeric = diagnostics["numericCapture"]
        capture_id = numeric["captureId"]
        metadata = {
            "captureId": capture_id,
            "sessionId": self._session_id, "generation": self._generation,
            "revision": request.revision, "gestureId": request.gesture_id,
            "motionRevision": motion_revision, "mode": mode, "trigger": request.trigger,
            "timing": dict(diagnostics["timing"]),
            "modelBeforeCapture": dict(diagnostics.get("modelBeforeCapture") or {}),
            "wheelCenter": dict(diagnostics["wheelCenter"]),
            "visualMaxRadius": self._max_radius,
            "observationResult": result, "observationReason": reason,
            "actual": dict(actual) if actual is not None else None,
            # Evidence only: preserve the original winner/shape/confidence so
            # the archived frame can distinguish a handle from a rim marking.
            # No extra detector pass or change to candidate selection.
            "handleDetection": dict(handle_detection) if handle_detection is not None else None,
        }
        try:
            submitted = plan.submit(bitmap, metadata)
            if not isinstance(submitted, dict):
                raise TypeError("numeric capture submit must return a JSON dictionary")
            diagnostics["numericCapture"] = {**numeric, **submitted, "captureId": capture_id}
        except Exception as exc:
            numeric.update(status="failed", reason="submit_failed", detail=str(exc))

    def _failure(
        self,
        request: _ObservationRequest,
        reason: str,
        started_at: float,
        detail: str = "",
        *,
        diagnostics: Optional[dict] = None,
    ) -> dict:
        finished_at = self._clock()
        result = {
            **(diagnostics or {}),
            "kind": "passive_observer",
            "phase": "sample",
            "result": "failed",
            "reason": reason,
            "sessionId": self._session_id,
            "generation": self._generation,
            "revision": request.revision,
            "gestureId": request.gesture_id,
            "trigger": request.trigger,
            "mode": request.mode,
            "totalMs": max(0.0, (finished_at - started_at) * 1000.0),
            "observerOnly": self._observer_only,
        }
        if diagnostics is not None:
            result["timing"] = {
                **diagnostics["timing"], "observationFinishedAt": finished_at
            }
        if detail:
            result["detail"] = detail
        return result

    def _trace(self, event: dict) -> None:
        try:
            self._trace_callback(event)
        except Exception:
            pass


__all__ = ["PassiveWheelObserver", "detect_neutral_handle"]
