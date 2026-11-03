"""Geometry helpers for the wheel overlay display."""

from .config import (
    OVERLAY_WHEEL_DOT_OUTSIDE_GAP,
    OVERLAY_WHEEL_RING_FALLBACK_RATIO,
)


def wheel_overlay_outer_control_radius(area, center_x, center_y, wheel_radius, outside_gap=None):
    if wheel_radius and wheel_radius > 0:
        base_radius = float(wheel_radius)
    else:
        base_radius = max(6.0, min(area['w'], area['h']) * OVERLAY_WHEEL_RING_FALLBACK_RATIO)

    gap = OVERLAY_WHEEL_DOT_OUTSIDE_GAP if outside_gap is None else float(outside_gap)
    return max(6.0, base_radius + gap)


__all__ = ['wheel_overlay_outer_control_radius']
