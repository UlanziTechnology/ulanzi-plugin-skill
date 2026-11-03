"""Confirm a persistent inward offset of an intended outer orbit, without I/O."""
from __future__ import annotations

import math
from .geometry import Vec2


class OrbitDriftGuard:
    def __init__(self, center: Vec2, radius: float) -> None:
        self.center, self.radius = center, radius
        self.reset()

    def reset(self) -> None:
        self.pending = False
        self.count = 0
        self.gesture = None
        self.vector = None
        self.first_at = self.last_at = None
        self.revision = -1

    def near_captured_path(self, expected, current):
        """Output frames can advance while a screenshot is being decoded.

        This tolerance admits evidence only, never a geometric commit. Keep
        both points on the same radius so a mode change cannot look current.
        """
        return (isinstance(expected, Vec2) and isinstance(current, Vec2)
                and (current - expected).length <= max(3, .08 * self.radius)
                and abs((current - self.center).length
                        - (expected - self.center).length) <= 1e-4)

    def recent_probe(self, observation, expected, current, now):
        """A superseded input revision may only request a fresh checkpoint."""
        try:
            timing = observation.get('timing') or {}
            started = float(timing['captureStartedAt'])
            finished = float(timing['observationFinishedAt'])
            return (math.isfinite(now) and started <= finished <= now
                    and 0 <= now - started <= .100
                    and observation.get('mode') == 'orbit'
                    and self.near_captured_path(expected, current))
        except (TypeError, ValueError, KeyError, AttributeError):
            return False

    def sample(self, observation, actual, expected, current, mode, *, current_motion,
               fresh_stationary=False):
        """Three distinct, coherent samples authorize only this gesture.

        Radius loss distinguishes a shifted circle from ordinary tangential
        render latency. The first error vector is the reference: three noisy
        samples may not walk the candidate arbitrarily across the wheel.
        """
        try:
            handle = observation.get('handle') or {}
            confidence = float(handle.get('confidence', 0))
            at = float((observation.get('timing') or {}).get('observationFinishedAt'))
            revision = observation.get('revision')
            gesture = observation.get('gestureId')
            valid = (
                observation.get('result') == 'ready' and mode == 'orbit'
                and isinstance(actual, Vec2) and isinstance(expected, Vec2)
                and math.isfinite(confidence) and confidence >= .75
                and handle.get('candidateCount') == 1 and math.isfinite(at)
                and isinstance(revision, int) and not isinstance(revision, bool)
                and isinstance(gesture, int) and not isinstance(gesture, bool)
                and revision >= 0 and gesture >= 0
                and self.near_captured_path(expected, current)
            )
            if valid:
                a, p = actual - self.center, expected - self.center
                vector = actual - expected
                valid = (
                    .90 * self.radius <= p.length <= self.radius + 1e-6
                    and .30 * self.radius <= a.length <= self.radius + 2.5
                    and a.dot(p) > 0
                    and vector.length <= .65 * self.radius
                )
        except (TypeError, ValueError, AttributeError):
            valid = False
        if not valid:
            if not self.pending:
                self.reset()
            return False
        if self.pending:
            if (gesture != self.gesture or revision <= self.revision
                    or at <= self.last_at):
                return False
            # An entered recovery has already passed three independent drift
            # samples. Applying its entry threshold again can latch forever:
            # the recorded stationary loss was 6.431 px at a 6.448 px gate.
            # Confirm the same error vector, with all detection/geometry and
            # gesture checks intact, instead of re-triggering the detector.
            if fresh_stationary and vector.length <= 1.5:
                # The host may finish rendering the in-flight movement after
                # UP. A current stationary sample can prove recovery obsolete;
                # normal feedback then releases the existing fresh barrier.
                self.reset()
                return False
            coherent = (vector - self.vector).length <= max(3, .06 * self.radius)
            if coherent:
                self.revision, self.last_at = revision, at
            return coherent
        if p.length - a.length < max(4, .08 * self.radius):
            self.reset()
            return False
        if not current_motion:
            self.reset()
            return False
        if revision <= self.revision or (self.last_at is not None and at <= self.last_at):
            return False
        consistent = (gesture == self.gesture and self.vector is not None
                      and at - self.first_at <= 1.0
                      and (vector - self.vector).length <= max(2, .03 * self.radius))
        if not consistent:
            self.count, self.gesture, self.vector, self.first_at = 0, gesture, vector, at
        self.count += 1
        self.revision, self.last_at = revision, at
        if self.count >= 3 and at - self.first_at >= .040:
            self.pending = True
        return self.pending
