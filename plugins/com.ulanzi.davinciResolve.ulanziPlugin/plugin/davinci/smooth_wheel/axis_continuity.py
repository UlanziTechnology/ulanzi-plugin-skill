"""Diameter intent outlives a native drag session, but not an external edit."""

from dataclasses import replace
import math

from ..area_target_helpers import area_key
from ..config import WHEEL_DIAMETER_CENTER_STATE_RADIUS
from .geometry import Vec2, WheelModel


class DiameterContinuity:
    """One selected wheel's oriented axis. No position-cache TTL applies.

    The caller serializes access and invalidates on external input/context
    changes. Recognition remains authoritative for the coordinate along the
    line, never its angle. Outside the centre band, large perpendicular errors
    invalidate the record rather than projecting a changed grade onto an old
    line. Near centre, a few pixels of transverse offset do not establish a
    reliable new direction; an otherwise valid owned axis remains authoritative.
    """

    def __init__(self):
        self._state = None
        self.last_decision = "empty"

    def invalidate(self):
        self._state = None
        self.last_decision = "invalidated"

    @staticmethod
    def _key(area):
        try:
            bounds = tuple(float(area[name]) for name in ("x", "y", "w", "h"))
            if not all(math.isfinite(value) for value in bounds):
                return None
            return area_key(area), bounds
        except (KeyError, TypeError, ValueError):
            return None

    def remember(self, area, calibration, statistics=None):
        key = self._key(area)
        if key is None or not calibration.valid:
            return False
        try:
            stats = statistics or {}
            point = stats.get("modelHandle")
            handle = Vec2(float(point["x"]), float(point["y"])) if point else calibration.handle
            model = WheelModel(calibration.center, handle, max(calibration.max_radius, (handle - calibration.center).length))
            axis = stats.get("diameterAxis")
            if axis:
                last = stats.get("lastNonzeroAxis")
                model.seed_diameter_state(
                    Vec2(float(axis["x"]), float(axis["y"])),
                    float(stats["signedRadius"]),
                    diameter_last_side=stats.get("diameterLastSide"),
                    last_nonzero_axis=Vec2(float(last["x"]), float(last["y"])) if last else None,
                )
            elif calibration.diameter_axis is not None and calibration.signed_radius is not None:
                model.seed_diameter_state(
                    calibration.diameter_axis, calibration.signed_radius,
                    diameter_last_side=calibration.diameter_last_side,
                    last_nonzero_axis=calibration.last_nonzero_axis,
                )
            elif model.radius <= 1e-9:
                model.seed_center_axis(calibration.rim - calibration.center)
        except (TypeError, ValueError, KeyError, OverflowError):
            return False
        # Effective clamps may expire with the position cache or be learned
        # during a gesture. They are not evidence of a window/layout change.
        radius = calibration.visual_radius or calibration.max_radius
        self._state = (key, calibration.center, radius,
                       model.diameter_axis, model.diameter_last_side,
                       model.last_nonzero_axis)
        return True

    def restore(self, area, calibration, *, preserve_center_axis=False):
        if self._state is None or not calibration.valid:
            self.last_decision = "empty"
            return calibration
        key, center, radius, axis, side, last_axis = self._state
        fresh_key = self._key(area)
        if (fresh_key is None or key[0] != fresh_key[0]
                or any(abs(a - b) > 0.5 for a, b in zip(key[1], fresh_key[1]))
                or (center - calibration.center).length > 0.5
                or abs(radius - (calibration.visual_radius or calibration.max_radius)) > 2.0):
            self.invalidate()
            self.last_decision = "geometry_changed"
            return calibration
        offset = calibration.handle - calibration.center
        signed = offset.dot(axis)
        perpendicular = (offset - axis * signed).length
        center_axis_preserved = (
            preserve_center_axis
            and perpendicular > 2.0
            and offset.length <= WHEEL_DIAMETER_CENTER_STATE_RADIUS
        )
        # A stopped/rearmed radial gesture must not turn a small transverse
        # displacement at centre into a new diameter. Keep only the trusted
        # direction; the fresh point still supplies the coordinate along it.
        # External input invalidation and geometry checks above remain gates,
        # and the original 2px off-axis protection still applies outside 7px.
        if perpendicular > 2.0 and not center_axis_preserved:
            self.invalidate()
            self.last_decision = "off_axis"
            return calibration
        if side == 0 and offset.length <= 2.0:
            # A verified reset has no previous side. Do not let its noisy
            # centre component flip the new north-facing marker before input.
            signed = 0.0
        if abs(signed) > 1e-9:
            side = 1 if signed > 0.0 else -1
            last_axis = axis * side
        else:
            signed = 0.0
        self.last_decision = "reused_center_axis" if center_axis_preserved else "reused"
        return replace(calibration, handle=calibration.center + axis * signed,
                       diameter_axis=axis, signed_radius=signed,
                       diameter_last_side=side, last_nonzero_axis=last_axis)
