"""macOS wheel pacing; shares the mouse owner with ordinary slider tasks.

Cadence is measured at input, never from worker throughput. Like the Resolve
runner, output consumes submitted distance at 120 Hz without catch-up bursts.
Host-specific relative mouse gain remains in the Jianying backend.
"""

from collections import deque
from copy import deepcopy
import math
import time

from .base import CoalescingAdjustmentQueue
from wheel_cadence import CadenceGain


class WheelAdjustmentQueue(CoalescingAdjustmentQueue):
    frame_seconds = 1.0 / 120.0
    wheel_drag_mode = "colorWheel"

    def __init__(self, performer):
        self._cadence = CadenceGain()
        self._wheel_key = None
        self._direction = 0
        self._generation = 0
        self._speed = 0.0
        self._arrivals = deque(maxlen=8)
        super().__init__(performer)

    @staticmethod
    def wheel_identity(calibration):
        return tuple(calibration.get(k) for k in (
            "targetKey", "centerX", "centerY", "wheelRadius", "scanVersion",
            "wheelMode", "sensitivity",
        ))

    def _drop_wheels_locked(self):
        self._pending = deque(t for t in self._pending
                              if not t["calibration"].get("_wheelFrame"))
        self._generation += 1
        self._speed = 0.0
        self._arrivals.clear()

    def submit(self, calibration, ticks, fine=False, replace_pending_hover=False):
        if calibration.get("dragMode") != self.wheel_drag_mode:
            with self._condition:
                self._drop_wheels_locked()
                self._cadence.reset()
                self._wheel_key = None
            return super().submit(calibration, ticks, fine, replace_pending_hover)
        try:
            ticks = float(ticks)
            sensitivity = float(calibration.get("sensitivity", 1.0))
        except (TypeError, ValueError):
            return
        if not math.isfinite(ticks) or not math.isfinite(sensitivity) or not ticks:
            return
        sensitivity = min(4.0, max(0.25, sensitivity))
        direction = 1 if ticks > 0 else -1
        mode = calibration.get("wheelMode", "diameter")
        key = self.wheel_identity(calibration)
        now = time.monotonic()
        with self._condition:
            if key != self._wheel_key or direction != self._direction:
                # A deliberate reversal takes priority over any unplayed old
                # movement, including a frame waiting for the mouse lock.
                self._drop_wheels_locked()
            self._wheel_key, self._direction = key, direction
            sample = self._cadence.sample(
                "tourbox_like" if mode == "orbit" else "push_pull_mild",
                "orbit" if mode == "orbit" else "push_pull",
                direction, key, now,
            )
            interval = sample["intervalMs"]
            if sample["reset"] or interval is None or interval >= 200:
                self._arrivals.clear()
            if interval is not None:
                self._arrivals.append(interval / 1000.0)
            # Resolve's fine baseline: 1 degree or 1 white-handle pixel per
            # detent. Batched host ticks are distance, not fake timing samples.
            amount = ticks * sensitivity * sample["gain"]
            field = "orbitFrameScale" if mode == "orbit" else "radialFrameScale"
            task = {
                "calibration": deepcopy(calibration), "ticks": amount,
                "fine": False, "scale": sample[field],
            }
            task["calibration"].update({
                "_wheelFrame": True, "_wheelGeneration": self._generation,
                "sensitivity": 1.0,
            })
            if (self._pending and self._pending[-1]["calibration"].get("_wheelFrame")
                    and self._pending[-1]["scale"] == task["scale"]):
                self._pending[-1]["ticks"] += amount
            else:
                self._pending.append(task)
            self._condition.notify()

    def is_current(self, calibration):
        with self._condition:
            return calibration.get("_wheelGeneration") == self._generation

    def clear(self):
        with self._condition:
            self._pending.clear()
            self._drop_wheels_locked()
            self._cadence.reset()
            self._wheel_key = None
            self._condition.notify()

    def _take_frame_locked(self):
        task = self._pending[0]
        if not task["calibration"].get("_wheelFrame"):
            return self._pending.popleft()
        orbit = task["calibration"].get("wheelMode") == "orbit"
        base, ceiling, acceleration = (0.75, 3.0, 0.35) if orbit else (0.5, 1.5, 0.2)
        distance = sum(abs(t["ticks"]) for t in self._pending
                       if t["calibration"].get("_wheelFrame"))
        limit = min(ceiling, base * task["scale"])
        # Brake from remaining submitted distance; no invented momentum.
        stop_frames = max(1, math.ceil((math.sqrt(1 + 8 * distance / acceleration) - 1) / 2))
        brake = distance / stop_frames + acceleration * (stop_frames - 1) / 2
        limit = min(limit, max(base, self._speed + acceleration), max(base, brake))
        # Blend sustained orbit input over its measured spacing. A single
        # precision detent remains immediate; no prediction adds distance.
        if orbit and len(self._arrivals) >= 6 and max(self._arrivals) <= .120:
            horizon = min(.075, max(.045, sum(self._arrivals) / len(self._arrivals)))
            limit = min(limit, max(.15, distance * self.frame_seconds / horizon))
        amount = math.copysign(min(abs(task["ticks"]), limit), task["ticks"])
        task["ticks"] -= amount
        self._speed = abs(amount)
        result = {"calibration": dict(task["calibration"]),
                  "ticks": amount / (4.0 if orbit else 1.8), "fine": False}
        if abs(task["ticks"]) < 1e-9:
            self._pending.popleft()
        return result

    def _expire_input_locked(self, now):
        """Optional host policy; macOS retains its submitted-distance pacing."""
        return False

    def _run(self):
        deadline = 0.0
        while True:
            with self._condition:
                while not self._pending:
                    self._speed = 0.0
                    self._condition.wait()
                    deadline = time.monotonic()
                if self._expire_input_locked(time.monotonic()):
                    continue
                delay = deadline - time.monotonic()
                if delay > 0:
                    self._condition.wait(delay)
                    continue
                task = self._take_frame_locked()
            try:
                result = self.performer(**task)
                if isinstance(result, dict) and result.get("boundary"):
                    with self._condition:
                        if self.is_current(task["calibration"]):
                            self._drop_wheels_locked()
            except Exception as exc:
                self.clear()
                print(f"mouse adjustment failed: {exc}")
            # Include performer time; a stall never triggers a catch-up burst.
            deadline = max(deadline + self.frame_seconds, time.monotonic() + .001)
