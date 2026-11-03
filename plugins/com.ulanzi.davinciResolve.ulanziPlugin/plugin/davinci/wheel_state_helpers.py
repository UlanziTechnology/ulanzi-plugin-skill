"""Pure helpers for sharing wheel state between controllers."""

from .wheel_state_radius_policy import (
    float_radius_value,
    should_store_effective_max_radius,
)


def wheel_state_value(source, key):
    if isinstance(source, dict):
        return source.get(key)
    return None


def coerce_effective_max_radius(value):
    return should_store_effective_max_radius(value)


def resolve_effective_max_radius(*sources):
    values = []
    for source in sources:
        value = (
            wheel_state_value(source, 'effective_max_radius')
            if isinstance(source, dict)
            else source
        )
        value = coerce_effective_max_radius(value)
        if value is not None:
            values.append(value)
    return min(values) if values else None


def clamp_max_radius_with_effective(max_radius, effective_max_radius):
    max_radius = float_radius_value(max_radius)
    effective_max_radius = coerce_effective_max_radius(effective_max_radius)
    if max_radius is None:
        return effective_max_radius
    if effective_max_radius is not None and effective_max_radius < max_radius:
        return effective_max_radius
    return max_radius


def resolve_outer_control_radius(*sources):
    for source in sources:
        value = wheel_state_value(source, 'outer_control_radius')
        value = float_radius_value(value)
        if value is not None and value > 0:
            return value
    return None


__all__ = [
    'clamp_max_radius_with_effective',
    'coerce_effective_max_radius',
    'resolve_effective_max_radius',
    'resolve_outer_control_radius',
    'wheel_state_value',
]
