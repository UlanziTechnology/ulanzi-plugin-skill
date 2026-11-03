# Copyright (c) Ulanzi DaVinci Resolve plugin contributors.
# Migrated from this project's validated gesture lab (tourbox-wheel-lab/host-test/.../wheel_worker/motion.py, v0.1.20).
# This is first-party experimental code promoted into the formal candidate;
# keep host-specific pointer and recognition policy outside this pure core.

"""Bounded, memoryless-output detent acceleration (no momentum after input)."""

from __future__ import annotations

import math


class CadenceGain:
    """Estimate cadence only within a same-direction, same-context gesture.

    The curve is a tunable lab preset, not a claim to reproduce TourBox's
    proprietary curve. Gain changes the submitted delta; measured fast orbit
    input also carries a bounded frame-scale hint, without changing runner rate.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._previous = None
        self._key = None
        self._interval = None
        self._flick_until = None
        self._flick_started = None
        self._flick_ready = False
        self._flick_strength = 0.0

    def sample(self, profile: str, mode: str, direction: float, context: object,
               now: float) -> dict:
        key = (profile, mode, direction, context)
        interval = None if self._previous is None else now - self._previous
        paused_orbit = (key == self._key and profile == "tourbox_like"
                        and mode == "orbit" and interval is not None
                        and math.isfinite(interval) and interval >= 0.2)
        fresh = (key != self._key or interval is None or not math.isfinite(interval)
                 or interval <= 0.0 or interval >= 0.5)
        self._key = key
        self._previous = now
        if fresh or profile == "raw":
            self._interval = None
            self._flick_until = None
            self._flick_started = None
            self._flick_strength = 0.0
            # After a long idle require a clearly fast next interval; a
            # normal medium-speed start must keep its established curve.
            self._flick_ready = 0.035 if paused_orbit else 0.0
            return {"gain": 1.0, "intervalMs": None, "reset": fresh,
                    "orbitFrameScale": 1.0, "radialFrameScale": 1.0, "flickAttack": 0.0}
        # A deliberate slow step must lose the old fast gain immediately.
        if interval >= 0.2:
            self._interval = interval
            self._flick_until = None
            self._flick_started = None
            self._flick_ready = 0.050 if paused_orbit else 0.0
        elif (profile == "tourbox_like" and mode == "orbit"
              and self._flick_ready and interval <= self._flick_ready):
            # A short, fast flick after a finger-repositioning pause should
            # not spend its few ticks averaging away that pause. The pause
            # itself still gets 1x; only a subsequent measured fast interval
            # restarts the filter. Continuous medium turns and push/pull
            # retain their established smoothing and curve.
            self._interval = interval
            self._flick_until = now + 0.150
            self._flick_started = now
            self._flick_strength = (
                max(0.0, min(1.0, (0.035 - interval) / 0.010))
                if self._flick_ready == 0.035 else 1.0
            )
            self._flick_ready = False
        else:
            self._flick_ready = False
            self._interval = (interval if self._interval is None else
                              0.5 * interval + 0.5 * self._interval)
            if profile == "push_pull_mild" and mode == "push_pull" and interval < 0.080:
                # Respond to the measured quick turn even after a short
                # finger pause. A 199 ms pause must not suppress a flick
                # that would recover after a 201 ms pause. Gradually remove
                # stale cadence history over 80–60 ms; medium/slow samples
                # retain the established filter. Fresh/reversed input still
                # returns 1x above, before any measured interval is available.
                recovery = max(0.0, min(1.0, (0.080 - interval) / 0.020))
                recovery = recovery * recovery * (3.0 - 2.0 * recovery)
                self._interval += (interval - self._interval) * recovery
        # Push/pull shares the reset/smoothing policy, not orbit's 4x curve.
        # Keep precision at low cadence and bound the extra queued distance;
        # frame size, diameter geometry and pointer transport stay unchanged.
        points = (
            ((0.035, 1.8), (0.070, 1.4), (0.120, 1.15), (0.200, 1.0))
            if profile == "push_pull_mild"
            else ((0.035, 4.0), (0.070, 2.5), (0.120, 1.5), (0.200, 1.0))
        )
        gain = 1.0
        if self._interval <= points[0][0]:
            gain = points[0][1]
        else:
            for (lo, high_gain), (hi, low_gain) in zip(points, points[1:]):
                if self._interval <= hi:
                    mix = (self._interval - lo) / (hi - lo)
                    gain = high_gain + mix * (low_gain - high_gain)
                    break
        gain = max(1.0, min(points[0][1], gain))
        # Give only the identified short flick a brief extra lift. Continuous
        # turns keep the original curve; slower input cancels the window,
        # and a 35–50 ms taper avoids a step at the fast/medium boundary.
        # Sustained fast input needs enough output capacity even without a
        # flick bonus: 4 degrees every 30 ms exceeds the ordinary 90 deg/s.
        # Require BOTH actual and filtered cadence to be fast. This releases
        # permission immediately on slowing, without increasing the distance.
        fast_cadence = (
            max(0.0, min(1.0, (0.050 - max(interval, self._interval)) / 0.015))
            if profile == "tourbox_like" and mode == "orbit" else 0.0
        )
        frame_scale = 1.0 + 3.0 * fast_cadence
        attack = 0.0
        if self._flick_until is not None:
            if now >= self._flick_until or interval >= 0.050:
                self._flick_until = None
                self._flick_started = None
            else:
                fast_interval = max(interval, self._interval)
                boost = max(0.0, min(1.0, (0.050 - fast_interval) / 0.015))
                boost *= self._flick_strength
                # Ease in the extra distance over 60 ms. The engine controls
                # output acceleration separately so this ramp cannot delay
                # delivery of already submitted motion.
                # Wall time, not callback count, prevents a coalesced burst
                # from reaching full gain immediately. Keep the original
                # 150 ms expiry; never repay the reduced start as momentum.
                phase = max(0.0, min(1.0, (now - self._flick_started) / 0.060))
                attack = 0.25 + 0.75 * phase * phase * (3.0 - 2.0 * phase)
                boost *= attack
                gain *= 1.0 + 1.5 * boost
        radial_scale = 1.0
        if profile == "push_pull_mild" and mode == "push_pull":
            # Extra radial distance is reserved for measured fast input.
            # Match its output capacity to the extra distance so a quick
            # turn does not leave a long tail at the ordinary 60 px/s limit.
            radial_fast = max(0.0, min(1.0, (0.075 - max(interval, self._interval)) / 0.040))
            radial_fast = radial_fast * radial_fast * (3.0 - 2.0 * radial_fast)
            gain *= 1.0 + radial_fast
            radial_scale = 1.0 + 2.0 * radial_fast
        return {"gain": gain,
                "intervalMs": interval * 1000.0, "reset": False,
                "orbitFrameScale": frame_scale, "radialFrameScale": radial_scale,
                "flickAttack": attack}
