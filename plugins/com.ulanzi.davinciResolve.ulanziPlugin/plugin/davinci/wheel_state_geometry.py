"""Geometry identity helpers for shared wheel state."""

from .config import (
    WHEEL_STATE_AREA_TOLERANCE_PX,
    WHEEL_STATE_CENTER_TOLERANCE_PX,
    WHEEL_STATE_RADIUS_TOLERANCE_PX,
)
from .wheel_state_radius_policy import float_radius_value


def wheel_state_area_bounds(area):
    if not area:
        return None
    return (
        float_radius_value(area.get('x')),
        float_radius_value(area.get('y')),
        float_radius_value(area.get('w')),
        float_radius_value(area.get('h')),
    )


def wheel_state_geometry_signature(area, center_x=None, center_y=None):
    bounds = wheel_state_area_bounds(area)
    if not bounds:
        return None
    center_x = float_radius_value(center_x)
    center_y = float_radius_value(center_y)
    values = list(bounds)
    if center_x is not None and center_y is not None:
        values.extend([center_x, center_y])
    return tuple(None if value is None else round(float(value), 1) for value in values)


def wheel_state_bounds_match(left, right):
    if not left or not right:
        return True
    for left_value, right_value in zip(left, right):
        if left_value is None or right_value is None:
            continue
        if abs(left_value - right_value) > WHEEL_STATE_AREA_TOLERANCE_PX:
            return False
    return True


def wheel_state_center_matches(state_center_x, state_center_y, center_x, center_y):
    state_center_x = float_radius_value(state_center_x)
    state_center_y = float_radius_value(state_center_y)
    center_x = float_radius_value(center_x)
    center_y = float_radius_value(center_y)
    if (
        state_center_x is None
        or state_center_y is None
        or center_x is None
        or center_y is None
    ):
        return True
    return (
        abs(state_center_x - center_x) <= WHEEL_STATE_CENTER_TOLERANCE_PX
        and abs(state_center_y - center_y) <= WHEEL_STATE_CENTER_TOLERANCE_PX
    )


def wheel_state_radius_mismatch(state_radius, wheel_radius):
    state_radius = float_radius_value(state_radius)
    wheel_radius = float_radius_value(wheel_radius)
    return (
        state_radius is not None
        and wheel_radius is not None
        and abs(state_radius - wheel_radius) > WHEEL_STATE_RADIUS_TOLERANCE_PX
    )


__all__ = [
    'wheel_state_area_bounds',
    'wheel_state_bounds_match',
    'wheel_state_center_matches',
    'wheel_state_geometry_signature',
    'wheel_state_radius_mismatch',
]
