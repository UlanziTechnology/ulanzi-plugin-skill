"""Windows wheel pacing with bounded, interruptible fixed-detent batches."""

from collections import deque
from copy import deepcopy
import math
import time

from .base import CoalescingAdjustmentQueue
from .wheel_queue import WheelAdjustmentQueue


class WindowsWheelAdjustmentQueue(WheelAdjustmentQueue):
    wheel_drag_mode = "windowsColorWheel"
    input_silence_seconds = 0.120
    fixed_batch_ticks = 2
    fixed_max_pending_ticks = 8
    fixed_input_silence_seconds = 0.180
    fixed_pending_silence_seconds = 0.060

    def __init__(self, performer, invalidate=None, fixed_input=None):
        self._invalidate = invalidate
        self._fixed_input = fixed_input
        self._input_profile = None
        self._last_wheel_input = None
        self._fixed_generation = 0
        self._fixed_key = None
        self._fixed_direction = 0
        self._fixed_last_input = None
        self._fixed_dispatched = False
        self._fixed_dropped_ticks = 0
        super().__init__(performer)
        print("windows fixed wheel queue: "
              f"batchTicks={self.fixed_batch_ticks} maxPendingTicks={self.fixed_max_pending_ticks} "
              f"silenceMs={self.fixed_pending_silence_seconds * 1000:.0f} "
              f"gestureGapMs={self.fixed_input_silence_seconds * 1000:.0f}")

    @staticmethod
    def wheel_identity(calibration):
        target = calibration.get("hoverTarget") or {}
        rect = target.get("windowRect") or {}
        return (WheelAdjustmentQueue.wheel_identity(calibration)
                + (calibration.get("motionContext"),)
                + tuple(target.get(k) for k in ("windowHwnd", "processId", "dpi"))
                + tuple(rect.get(k) for k in ("x", "y", "w", "h")))

    def _drop_wheels_locked(self):
        super()._drop_wheels_locked()
        self._retire_fixed_locked()
        self._last_wheel_input = None
        if self._invalidate:
            self._invalidate(self._generation)

    def _input_expired_locked(self, now):
        return (self._input_profile == "accelerated"
                and self._last_wheel_input is not None
                and now - self._last_wheel_input >= self.input_silence_seconds)

    def _expire_input_locked(self, now):
        if self._input_profile == "fixed":
            # Do not cancel an isolated first detent just because recognition or
            # mouse preparation was slow. Expire only unstarted backlog here;
            # the independent native input signal also guards running waits.
            if (not self._fixed_dispatched or self._fixed_last_input is None
                    or now - self._fixed_last_input < self.fixed_pending_silence_seconds):
                return False
            distance = self._fixed_pending_ticks()
            if not distance:
                return False
            self._pending = deque(t for t in self._pending
                                  if not t["calibration"].get("_fixedWheel"))
            print("windows fixed wheel stop: reason=input_silence "
                  f"ageMs={(now - self._fixed_last_input) * 1000:.1f} "
                  f"droppedTicks={distance} generation={self._fixed_generation} "
                  f"monotonicMs={now * 1000:.1f}")
            return True
        if not self._input_expired_locked(now):
            return False
        age_ms = (now - self._last_wheel_input) * 1000
        distance = sum(abs(t["ticks"]) for t in self._pending
                       if t["calibration"].get("_wheelFrame"))
        self._drop_wheels_locked()
        self._cadence.reset()
        self._wheel_key = None
        print(f"windows wheel queue stop: reason=input_silence ageMs={age_ms:.1f} "
              f"droppedDistance={distance:.4f} generation={self._generation}")
        return True

    def is_current(self, calibration):
        if calibration.get("_fixedWheel"):
            # An atomic integer read is enough for the transport's final guard;
            # never take the queue lock while the transport holds its write lock.
            return calibration.get("_fixedWheelGeneration") == self._fixed_generation
        with self._condition:
            return (super().is_current(calibration)
                    and not self._input_expired_locked(time.monotonic()))

    def discard_if_current(self, calibration):
        with self._condition:
            if self.is_current(calibration):
                self.clear()
                return True
            return False

    def _fixed_pending_ticks(self):
        return sum(abs(t["ticks"]) for t in self._pending
                   if t["calibration"].get("_fixedWheel"))

    def _retire_fixed_locked(self):
        self._pending = deque(t for t in self._pending
                              if not t["calibration"].get("_fixedWheel"))
        self._fixed_generation += 1
        self._fixed_key = None
        self._fixed_last_input = None
        self._fixed_dispatched = False
        self._fixed_dropped_ticks = 0
        if self._fixed_input:
            self._fixed_input(self._fixed_generation, None)

    def _submit_fixed(self, calibration, ticks, fine, replace_pending_hover):
        try:
            value = float(ticks)
            if not math.isfinite(value):
                return
            ticks = int(round(value))
        except (TypeError, ValueError, OverflowError):
            return
        if not ticks:
            return
        now = time.monotonic()
        key = self.wheel_identity(calibration) + (bool(fine),)
        direction = 1 if ticks > 0 else -1
        with self._condition:
            # The worker may still be preparing a drag. Expire its old backlog
            # before this new arrival renews the timestamp within the same gesture.
            self._expire_input_locked(now)
            new_gesture = (key != self._fixed_key
                           or direction != self._fixed_direction
                           or self._fixed_last_input is None
                           or now - self._fixed_last_input >= self.fixed_input_silence_seconds)
            if new_gesture:
                dropped = self._fixed_pending_ticks()
                self._retire_fixed_locked()
                if replace_pending_hover:
                    self._pending = deque(t for t in self._pending
                                          if not isinstance(t["calibration"].get("hoverTarget"), dict))
                if dropped:
                    print("windows fixed wheel stop: reason=new_gesture "
                          f"droppedTicks={dropped} generation={self._fixed_generation} "
                          f"monotonicMs={now * 1000:.1f}")
            self._fixed_key, self._fixed_direction = key, direction
            self._fixed_last_input = now
            if self._fixed_input:
                self._fixed_input(self._fixed_generation, now)
            task = {"calibration": deepcopy(calibration), "ticks": ticks, "fine": bool(fine)}
            task["calibration"].update(_fixedWheel=True, _fixedWheelGeneration=self._fixed_generation)
            if self._pending and self._pending[-1]["calibration"].get("_fixedWheel"):
                self._pending[-1]["ticks"] += ticks
            else:
                self._pending.append(task)
            pending = self._pending[-1]
            excess = max(0, abs(pending["ticks"]) - self.fixed_max_pending_ticks)
            if excess:
                pending["ticks"] = direction * self.fixed_max_pending_ticks
                self._fixed_dropped_ticks += excess
            self._condition.notify()

    def _take_frame_locked(self):
        task = self._pending[0]
        if not task["calibration"].get("_fixedWheel"):
            return super()._take_frame_locked()
        ticks = (1 if task["ticks"] > 0 else -1) * min(abs(task["ticks"]), self.fixed_batch_ticks)
        task["ticks"] -= ticks
        result = {"calibration": dict(task["calibration"]), "ticks": ticks, "fine": task["fine"]}
        result["calibration"]["_fixedWheelFirstBatch"] = not self._fixed_dispatched
        result["calibration"]["_fixedWheelInputMs"] = self._fixed_last_input * 1000.0
        if not task["ticks"]:
            self._pending.popleft()
        self._fixed_dispatched = True
        now = time.monotonic()
        print("windows fixed wheel dispatch: "
              f"ticks={ticks} pendingTicks={self._fixed_pending_ticks()} "
              f"trimmedTicks={self._fixed_dropped_ticks} "
              f"inputAgeMs={(now - self._fixed_last_input) * 1000:.1f} "
              f"generation={self._fixed_generation} monotonicMs={now * 1000:.1f}")
        self._fixed_dropped_ticks = 0
        return result

    def submit(self, calibration, ticks, fine=False, replace_pending_hover=False):
        is_wheel = calibration.get("dragMode") == self.wheel_drag_mode
        profile = calibration.get("wheelMotion", "fixed") if is_wheel else None
        with self._condition:
            if profile != self._input_profile:
                self._pending.clear()
                self._drop_wheels_locked()
                self._cadence.reset()
                self._wheel_key = None
            self._input_profile = profile
        if is_wheel and profile == "fixed":
            return self._submit_fixed(calibration, ticks, fine, replace_pending_hover)
        if is_wheel and profile == "accelerated":
            try:
                valid = math.isfinite(float(ticks)) and float(ticks) != 0
                valid = valid and math.isfinite(float(calibration.get("sensitivity", 1)))
            except (ValueError, TypeError):
                valid = False
            if not valid:
                return
            with self._condition:
                # Expire before a same-direction restart so fresh input cannot
                # revive an old queue. Reversals/profile changes still own their
                # existing generation invalidation.
                self._expire_input_locked(time.monotonic())
                super().submit(calibration, ticks, fine, replace_pending_hover)
                self._last_wheel_input = time.monotonic()
            return
        if not is_wheel:
            with self._condition:
                self._drop_wheels_locked()
                self._cadence.reset()
                self._wheel_key = None
        return CoalescingAdjustmentQueue.submit(
            self, calibration, ticks, fine, replace_pending_hover)
