"""Radius and outer-dot visual helpers for DaVinci color-wheel overlays."""

from .config import (
    OVERLAY_WHEEL_DOT_FALLBACK_OUTSIDE_GAP,
    OVERLAY_WHEEL_DOT_OUTSIDE_GAP,
    OVERLAY_WHEEL_OUTER_RADIUS_CACHE_TOLERANCE_PX,
    OVERLAY_WHEEL_OUTER_RADIUS_MAX_OUTWARD_JUMP_PX,
    OVERLAY_WHEEL_RING_FALLBACK_RATIO,
)
from .wheel_diameter_geometry import wheel_diameter_outer_control_point
from .wheel_overlay_geometry import wheel_overlay_outer_control_radius


def _positive_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def wheel_visual_radius(area, wheel_radius):
    radius = _positive_float(wheel_radius)
    if radius and 6 < radius < min(area['w'], area['h']) * 0.52:
        return radius
    return max(6.0, min(area['w'], area['h']) * OVERLAY_WHEEL_RING_FALLBACK_RATIO)


def _wheel_radius_is_detected(area, wheel_radius):
    radius = _positive_float(wheel_radius)
    return bool(radius and 6 < radius < min(area['w'], area['h']) * 0.52)


def resolve_wheel_outer_control_radius(
    area,
    center_x,
    center_y,
    visual_radius=None,
    wheel_radius=None,
    cached_outer_radius=None,
):
    base_radius = _positive_float(visual_radius)
    if base_radius is None:
        base_radius = wheel_visual_radius(area, wheel_radius)
    outside_gap = (
        OVERLAY_WHEEL_DOT_OUTSIDE_GAP
        if _wheel_radius_is_detected(area, wheel_radius)
        else OVERLAY_WHEEL_DOT_FALLBACK_OUTSIDE_GAP
    )

    resolved_radius = wheel_overlay_outer_control_radius(
        area,
        center_x,
        center_y,
        base_radius,
        outside_gap=outside_gap,
    )
    cached_radius = _positive_float(cached_outer_radius)
    if (
        cached_radius is not None
        and abs(cached_radius - resolved_radius) <= OVERLAY_WHEEL_OUTER_RADIUS_CACHE_TOLERANCE_PX
    ):
        return cached_radius
    if (
        cached_radius is not None
        and resolved_radius > cached_radius + OVERLAY_WHEEL_OUTER_RADIUS_MAX_OUTWARD_JUMP_PX
    ):
        return cached_radius
    return resolved_radius


def build_wheel_outer_visual(
    area,
    center_x,
    center_y,
    axis_angle,
    signed_radius,
    visual_radius=None,
    wheel_radius=None,
    cached_outer_radius=None,
):
    outer_radius = resolve_wheel_outer_control_radius(
        area,
        center_x,
        center_y,
        visual_radius=visual_radius,
        wheel_radius=wheel_radius,
        cached_outer_radius=cached_outer_radius,
    )
    outer_x, outer_y, control_angle = wheel_diameter_outer_control_point(
        center_x,
        center_y,
        axis_angle,
        signed_radius,
        outer_radius,
    )
    return {
        'outer_control_radius': outer_radius,
        'outer_control_x': outer_x,
        'outer_control_y': outer_y,
        'control_angle': control_angle,
    }


__all__ = [
    'build_wheel_outer_visual',
    'resolve_wheel_outer_control_radius',
    'wheel_visual_radius',
]
