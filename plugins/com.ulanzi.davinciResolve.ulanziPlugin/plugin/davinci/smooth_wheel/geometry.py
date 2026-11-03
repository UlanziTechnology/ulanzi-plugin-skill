# Copyright (c) Ulanzi DaVinci Resolve plugin contributors.
# Migrated from this project's validated gesture lab (tourbox-wheel-lab/src/tourbox_wheel_lab/geometry.py, v0.1.20).
# This is first-party experimental code promoted into the formal candidate;
# keep host-specific pointer and recognition policy outside this pure core.

"""Pure geometry for an interactive color-wheel handle.

The module deliberately knows nothing about mice, timers, DaVinci Resolve, or
device events.  Coordinates use the usual screen convention: ``x`` grows to
the right, ``y`` grows downwards, and therefore positive angles rotate
clockwise.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional


_EPSILON = 1e-12
# Visual handle centroids can move by a fraction of a pixel between otherwise
# identical screenshots.  A canonical diameter necessarily has one orientation
# seam; around the horizontal seam, use the established axis as a hysteresis
# reference instead of letting sub-pixel y noise reverse the signed coordinate.
# The observed point is never snapped: these values only choose between an
# exact normalized vector and its exact opposite.
_HORIZONTAL_AXIS_TOLERANCE_PX = 0.5
_HORIZONTAL_AXIS_TOLERANCE_RATIO = 0.01


@dataclass(frozen=True)
class Vec2:
    """A small immutable two-dimensional vector."""

    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vec2:
        return Vec2(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Vec2:
        return self * scalar

    def __truediv__(self, scalar: float) -> Vec2:
        if abs(scalar) <= _EPSILON:
            raise ZeroDivisionError("cannot divide a vector by zero")
        return Vec2(self.x / scalar, self.y / scalar)

    def dot(self, other: Vec2) -> float:
        return self.x * other.x + self.y * other.y

    @property
    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def normalized(self) -> Vec2:
        length = self.length
        if length <= _EPSILON:
            raise ValueError("a zero-length vector has no direction")
        return self / length

    def rotated_clockwise(self, degrees: float) -> Vec2:
        """Return this vector rotated by a screen-space clockwise angle."""

        radians = math.radians(degrees)
        cosine = math.cos(radians)
        sine = math.sin(radians)
        return Vec2(
            self.x * cosine - self.y * sine,
            self.x * sine + self.y * cosine,
        )


@dataclass(frozen=True)
class MotionResult:
    """Result of one orbit or push/pull operation.

    ``applied`` is the actual amount accepted by the model.  It is measured in
    degrees for :meth:`WheelModel.orbit` and pixels for
    :meth:`WheelModel.push_pull`.  A boundary clamp can make it smaller than
    the requested amount.
    """

    position: Vec2
    applied: float
    clamped: bool
    crossed_center: bool


class WheelModel:
    """Stateful geometry for one color-wheel handle.

    Push/pull uses a signed scalar on a canonical diameter axis that persists
    for the lifetime of the model.  A push/pull session only controls whether
    that axis is currently active; ending a pointer burst does not reconstruct
    the axis from the visible side of the handle.  Negative scalar values
    intentionally place the handle on the opposite side of the center.  This
    makes a center crossing a single straight segment and lets the same input
    direction continue naturally after an idle release.
    """

    def __init__(self, center: Vec2, handle: Vec2, max_radius: float) -> None:
        if not math.isfinite(max_radius) or max_radius <= 0.0:
            raise ValueError("max_radius must be a finite positive number")
        if not all(math.isfinite(value) for value in (center.x, center.y, handle.x, handle.y)):
            raise ValueError("center and handle coordinates must be finite")

        self.center = center
        # ``max_radius`` is the visually recognised wheel radius. Resolve can
        # stop accepting radial movement a little before that rim, so the
        # effective clamp is learned separately and may only shrink.
        self.max_radius = float(max_radius)
        self._effective_max_radius = self.max_radius

        offset = handle - center
        if offset.length > self.max_radius:
            offset = offset.normalized() * self.max_radius
        self._handle = center + offset

        # There is no observable hue at the exact center.  +X is the stable
        # default until a non-zero handle direction (or a center orbit) exists.
        self._last_nonzero_axis = (
            offset.normalized() if offset.length > _EPSILON else Vec2(1.0, 0.0)
        )

        # The diameter coordinate belongs to the logical wheel state, not to
        # an individual mouse-down burst.  In particular, once the handle has
        # crossed the center, rebuilding an axis from the visible handle would
        # reverse both the axis and the meaning of the next input delta.
        if offset.length > _EPSILON:
            self._diameter_axis, self._signed_radius = _canonical_diameter(offset)
        else:
            self._diameter_axis = self._last_nonzero_axis
            self._signed_radius = 0.0
        self._diameter_last_side = _sign(self._signed_radius)

        self._push_pull_axis: Optional[Vec2] = None

    @property
    def handle(self) -> Vec2:
        return self._handle

    @property
    def radius(self) -> float:
        return (self._handle - self.center).length

    @property
    def effective_max_radius(self) -> float:
        """Conservative radial limit currently used by push/pull."""

        return self._effective_max_radius

    @property
    def angle_degrees(self) -> float:
        """Displayed clockwise angle in ``[0, 360)``.

        At the exact center, the most recent non-zero direction is retained so
        subsequent motion does not acquire a random axis.
        """

        offset = self._handle - self.center
        axis = offset.normalized() if offset.length > _EPSILON else self._last_nonzero_axis
        return math.degrees(math.atan2(axis.y, axis.x)) % 360.0

    @property
    def last_nonzero_axis(self) -> Vec2:
        return self._last_nonzero_axis

    @property
    def diameter_axis(self) -> Vec2:
        """Stable oriented axis used by signed push/pull motion."""

        return self._diameter_axis

    @property
    def signed_radius(self) -> float:
        """Handle coordinate on :attr:`diameter_axis`."""

        return self._signed_radius

    @property
    def diameter_last_side(self) -> int:
        """Last non-centre side of the oriented push/pull diameter."""

        return self._diameter_last_side

    @property
    def push_pull_active(self) -> bool:
        return self._push_pull_axis is not None

    def seed_center_axis(self, axis: Vec2) -> Vec2:
        """Seed the otherwise unobservable direction of an exact-center handle.

        The formal plugin keeps a stable diameter direction while a wheel is at
        its centre.  Importing that direction at the arm boundary prevents the
        first push/pull or centre-orbit step from jumping to the geometry
        core's generic +X fallback.  A visible, non-centre handle always wins
        and is therefore never changed by this method.
        """

        if not all(math.isfinite(value) for value in (axis.x, axis.y)):
            raise ValueError("center axis coordinates must be finite")
        normalized = axis.normalized()
        if self.radius > _EPSILON:
            return self._last_nonzero_axis

        canonical, implied_side = _canonical_diameter(normalized)
        self._last_nonzero_axis = normalized
        self._diameter_axis = canonical
        self._signed_radius = 0.0
        self._diameter_last_side = _sign(implied_side)
        self._push_pull_axis = None
        return self._last_nonzero_axis

    def seed_diameter_state(
        self,
        axis: Vec2,
        signed_radius: float,
        *,
        diameter_last_side: Optional[int] = None,
        last_nonzero_axis: Optional[Vec2] = None,
    ) -> Vec2:
        """Restore a trusted oriented diameter without re-canonicalizing it.

        Visual detection treats a diameter as undirected and canonicalizes its
        orientation.  A running smooth model has stronger information: near
        the horizontal seam its orientation and the previous side are required
        to preserve the meaning of the next positive push/pull step.
        """

        if not all(math.isfinite(value) for value in (axis.x, axis.y)):
            raise ValueError("diameter axis coordinates must be finite")
        normalized = axis.normalized()
        parsed_radius = float(signed_radius)
        if not math.isfinite(parsed_radius):
            raise ValueError("signed radius must be finite")
        if abs(parsed_radius) > self._effective_max_radius + 1e-6:
            raise ValueError("signed radius exceeds the effective wheel radius")
        expected = self.center + normalized * parsed_radius
        if (expected - self._handle).length > 1e-3:
            raise ValueError("diameter state does not match the visible handle")

        parsed_side = _sign(parsed_radius)
        if diameter_last_side is not None:
            try:
                requested_side = int(diameter_last_side)
            except (TypeError, ValueError):
                raise ValueError("diameter_last_side must be -1, 0, or 1")
            if requested_side not in (-1, 0, 1):
                raise ValueError("diameter_last_side must be -1, 0, or 1")
            if parsed_side == 0:
                parsed_side = requested_side

        if last_nonzero_axis is None:
            remembered = normalized * (-1.0 if parsed_side < 0 else 1.0)
        else:
            if not all(
                math.isfinite(value)
                for value in (last_nonzero_axis.x, last_nonzero_axis.y)
            ):
                raise ValueError("last nonzero axis coordinates must be finite")
            remembered = last_nonzero_axis.normalized()
            if abs(parsed_radius) > _EPSILON:
                visible_axis = (self._handle - self.center).normalized()
                if remembered.dot(visible_axis) < 1.0 - 1e-6:
                    raise ValueError("last nonzero axis does not match the handle")

        self._diameter_axis = normalized
        self._signed_radius = parsed_radius
        self._diameter_last_side = parsed_side
        self._last_nonzero_axis = remembered
        self._push_pull_axis = None
        return self._diameter_axis

    def set_effective_max_radius(self, radius: float) -> float:
        """Shrink the radial clamp after an idle visual confirmation.

        Learning is deliberately monotonic for one armed session: a noisy
        screenshot cannot expand the allowed range beyond either the visual
        rim or a previously confirmed smaller host limit.
        """

        parsed = float(radius)
        if not math.isfinite(parsed) or parsed <= 0.0:
            raise ValueError("effective radius must be finite and positive")
        self._effective_max_radius = min(
            self._effective_max_radius, self.max_radius, parsed
        )
        return self._effective_max_radius

    def reconcile_handle(
        self,
        handle: Vec2,
        *,
        preserve_diameter_axis: bool = False,
    ) -> Vec2:
        """Adopt a confirmed idle handle while preserving signed semantics.

        The gesture engine is responsible for calling this only with no
        pointer session and no queued motion. A non-zero observation defines
        the canonical diameter and its sign. At the exact centre the previous
        direction is retained because the pixels contain no hue direction.

        When ``preserve_diameter_axis`` is true, the visual point is projected
        onto the already established diameter. Centre pixels can report a
        nearby colour or crosshair component whose polar angle is meaningless;
        projection may refine its signed radius without rotating that hidden
        direction.
        """

        if not all(math.isfinite(value) for value in (handle.x, handle.y)):
            raise ValueError("confirmed handle coordinates must be finite")
        offset = handle - self.center
        limit = self._effective_max_radius
        if offset.length > limit:
            offset = offset.normalized() * limit
        self._push_pull_axis = None
        if preserve_diameter_axis:
            signed_radius = max(
                -limit,
                min(limit, offset.dot(self._diameter_axis)),
            )
            self._signed_radius = signed_radius
            self._handle = self.center + self._diameter_axis * signed_radius
            new_side = _sign(signed_radius)
            if new_side != 0:
                self._diameter_last_side = new_side
                self._last_nonzero_axis = (
                    self._diameter_axis
                    if new_side > 0
                    else self._diameter_axis * -1.0
                )
            return self._handle

        self._handle = self.center + offset
        if offset.length > _EPSILON:
            self._diameter_axis, self._signed_radius = _canonical_diameter(
                offset,
                preferred_axis=self._diameter_axis,
            )
            self._diameter_last_side = _sign(self._signed_radius)
            self._last_nonzero_axis = offset.normalized()
        else:
            self._signed_radius = 0.0
        return self._handle

    def orbit(self, delta_degrees: float) -> MotionResult:
        """Rotate clockwise while preserving the current radius."""

        if not math.isfinite(delta_degrees):
            raise ValueError("delta_degrees must be finite")

        # Changing degree of freedom ends the previous frozen-axis session.
        self.end_push_pull()

        if abs(self._signed_radius) > _EPSILON:
            offset = self._diameter_axis * self._signed_radius
            rotated = offset.rotated_clockwise(delta_degrees)
            self._diameter_axis, self._signed_radius = _canonical_diameter(rotated)
            self._diameter_last_side = _sign(self._signed_radius)
            self._handle = self.center + rotated
            self._last_nonzero_axis = rotated.normalized()
        else:
            # A center has no visible side, so rotate the remembered display
            # direction and canonicalize the otherwise undirected diameter.
            rotated = self._last_nonzero_axis.rotated_clockwise(
                delta_degrees
            ).normalized()
            self._diameter_axis, implied_side = _canonical_diameter(rotated)
            if self._diameter_last_side != 0:
                self._diameter_last_side = _sign(implied_side)
            self._last_nonzero_axis = rotated
            self._handle = self.center

        return MotionResult(
            position=self._handle,
            applied=delta_degrees,
            clamped=False,
            crossed_center=False,
        )

    def begin_push_pull(self) -> Vec2:
        """Activate and return the persistent push/pull diameter axis.

        Calling this method while a session is active is idempotent.
        """

        if self._push_pull_axis is not None:
            return self._push_pull_axis

        self._push_pull_axis = self._diameter_axis
        return self._push_pull_axis

    def end_push_pull(self) -> None:
        """End the active session without discarding its diameter state."""

        self._push_pull_axis = None

    def push_pull(self, delta: float) -> MotionResult:
        """Move along the frozen diameter by ``delta`` pixels.

        The signed scalar is clamped directly to ``[-max_radius,
        max_radius]``.  Excess outward input is not retained, so a subsequent
        reverse input takes effect immediately.
        """

        if not math.isfinite(delta):
            raise ValueError("delta must be finite")
        axis = self.begin_push_pull()

        previous = self._signed_radius
        requested = previous + delta
        target = max(
            -self._effective_max_radius,
            min(self._effective_max_radius, requested),
        )
        clamped = not math.isclose(target, requested, rel_tol=0.0, abs_tol=_EPSILON)
        applied = target - previous

        new_side = _sign(target)
        crossed_center = (
            new_side != 0
            and self._diameter_last_side != 0
            and new_side != self._diameter_last_side
        )

        self._signed_radius = target
        self._handle = self.center + axis * target

        if new_side != 0:
            self._diameter_last_side = new_side
            self._last_nonzero_axis = axis if new_side > 0 else axis * -1.0

        return MotionResult(
            position=self._handle,
            applied=applied,
            clamped=clamped,
            crossed_center=crossed_center,
        )


def _sign(value: float) -> int:
    if value > _EPSILON:
        return 1
    if value < -_EPSILON:
        return -1
    return 0


def _canonical_diameter(
    offset: Vec2,
    preferred_axis: Optional[Vec2] = None,
) -> tuple[Vec2, float]:
    """Return a stable oriented diameter and its signed coordinate.

    A diameter is geometrically undirected, so opposite handle points must
    produce the same oriented axis.  Screen-space upper vectors (negative
    ``y``) are canonical and the horizontal tie is oriented toward +X.  During
    reconciliation, an established orientation wins inside the explicit
    sub-pixel/proportional seam band. The returned axis still follows the
    observed diameter exactly; only the choice between that vector and its
    opposite is stabilized. The scalar sign retains the occupied half.
    """

    radius = offset.length
    if radius <= _EPSILON:
        raise ValueError("a zero-length vector has no canonical diameter")

    axis = offset / radius
    horizontal_tolerance = max(
        _HORIZONTAL_AXIS_TOLERANCE_PX,
        radius * _HORIZONTAL_AXIS_TOLERANCE_RATIO,
    )
    if abs(offset.y) <= horizontal_tolerance and preferred_axis is not None:
        # Reconciliation already has a stable diameter. Select the exact
        # orientation closest to it while an observation is inside the
        # horizontal hysteresis band. This preserves physical push/pull
        # polarity across e.g. y=-0.1 -> y=+0.1 recognition noise.
        alignment = axis.dot(preferred_axis)
        should_flip = alignment < 0.0 or (
            abs(alignment) <= _EPSILON and axis.x < 0.0
        )
    else:
        # Initial construction and geometry outside the seam remain uniquely
        # canonical: upper screen half first, with the horizontal tie at +X.
        should_flip = offset.y > horizontal_tolerance or (
            abs(offset.y) <= horizontal_tolerance and axis.x < 0.0
        )
    if should_flip:
        return axis * -1.0, -radius
    return axis, radius
