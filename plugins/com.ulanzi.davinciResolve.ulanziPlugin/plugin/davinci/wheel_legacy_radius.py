"""Shared radius helpers for legacy wheel fallback paths."""

from .config import (
    WHEEL_EDGE_PADDING,
    WHEEL_HANDLE_EDGE_PADDING,
    WHEEL_HANDLE_MAX_RADIUS_RATIO,
    WHEEL_ROTATION_MIN_RADIUS,
)


def wheel_legacy_safe_radius(area, handle):
    wheel_radius = handle.get('wheel_radius')
    if wheel_radius:
        return max(
            WHEEL_ROTATION_MIN_RADIUS,
            min(
                max(WHEEL_ROTATION_MIN_RADIUS, wheel_radius - WHEEL_HANDLE_EDGE_PADDING),
                max(WHEEL_ROTATION_MIN_RADIUS, wheel_radius * WHEEL_HANDLE_MAX_RADIUS_RATIO),
            ),
        )
    return max(WHEEL_ROTATION_MIN_RADIUS, min(area['w'], area['h']) / 2 - WHEEL_EDGE_PADDING)


__all__ = ['wheel_legacy_safe_radius']
