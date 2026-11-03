"""Radius-field policies for shared wheel state."""

from .config import (
    OVERLAY_WHEEL_OUTER_RADIUS_MAX_OUTWARD_JUMP_PX,
    WHEEL_ROTATION_MIN_RADIUS,
)


def float_radius_value(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def should_store_effective_max_radius(value):
    value = float_radius_value(value)
    if value is None or value < WHEEL_ROTATION_MIN_RADIUS:
        return None
    return value


def should_store_outer_control_radius(value, current_outer_radius):
    value = float_radius_value(value)
    if value is None or value <= 0:
        return None
    current_outer = float_radius_value(current_outer_radius)
    if (
        current_outer is not None
        and value > current_outer + OVERLAY_WHEEL_OUTER_RADIUS_MAX_OUTWARD_JUMP_PX
    ):
        return None
    return value


__all__ = [
    'float_radius_value',
    'should_store_effective_max_radius',
    'should_store_outer_control_radius',
]
