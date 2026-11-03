"""Reuse policy for outer-anchor wheel state."""

from .config import WHEEL_ANCHOR_STATE_SECONDS, WHEEL_STATE_CACHE_SECONDS
from .wheel_state_geometry import (
    wheel_state_area_bounds,
    wheel_state_bounds_match,
    wheel_state_center_matches,
)


def _area_center(area):
    if not area:
        return None, None
    return (
        area.get('center_x', area['x'] + area['w'] / 2),
        area.get('center_y', area['y'] + area['h'] / 2),
    )


def wheel_anchor_geometry_matches(anchor, area):
    if not anchor or not area:
        return False

    anchor_area = anchor.get('area')
    if not wheel_state_bounds_match(
        wheel_state_area_bounds(anchor_area),
        wheel_state_area_bounds(area),
    ):
        return False

    center_x, center_y = _area_center(area)
    return wheel_state_center_matches(
        anchor.get('center_x'),
        anchor.get('center_y'),
        center_x,
        center_y,
    )


def wheel_anchor_is_reusable(anchor, target_key, now, area=None):
    if not (
        anchor
        and anchor.get('target_key') == target_key
        and anchor.get('updated_at') is not None
    ):
        return False
    if anchor.get('force_fresh_handle'):
        return False

    age = now - anchor.get('updated_at', 0)
    if age <= WHEEL_ANCHOR_STATE_SECONDS:
        return True
    if age > WHEEL_STATE_CACHE_SECONDS:
        return False
    return wheel_anchor_geometry_matches(anchor, area)


__all__ = [
    'wheel_anchor_geometry_matches',
    'wheel_anchor_is_reusable',
]
