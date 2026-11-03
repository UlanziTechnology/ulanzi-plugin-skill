"""Persistent wheel geometry and capability state."""

import time

from .config import WHEEL_STATE_CACHE_SECONDS
from .wheel_state_geometry import (
    wheel_state_area_bounds,
    wheel_state_bounds_match,
    wheel_state_center_matches,
    wheel_state_geometry_signature,
    wheel_state_radius_mismatch,
)
from .wheel_state_handle_payloads import wheel_last_detected_handle_snapshot
from .wheel_state_radius_policy import (
    float_radius_value,
    should_store_effective_max_radius,
    should_store_outer_control_radius,
)


_MISSING = object()


def _float_value(value):
    return float_radius_value(value)


class WheelStateStore:
    """Keeps learned wheel state across diameter/orbit controller handoffs."""

    def __init__(self):
        self._states = {}

    def clear(self):
        self._states.clear()

    def invalidate_handle(self, area_key, *, expected_handle):
        """Drop one stale point while retaining its measured wheel geometry."""
        state = self._states.get(area_key)
        if (state is not None and expected_handle is not None
                and state.get('last_detected_handle') is expected_handle):
            state.pop('last_detected_handle', None)

    def get(self, area_key, area=None, center_x=None, center_y=None, wheel_radius=None):
        if not area_key:
            return None
        state = self._states.get(area_key)
        if not state:
            return None
        if time.time() - state.get('updated_at', 0.0) > WHEEL_STATE_CACHE_SECONDS:
            self._states.pop(area_key, None)
            return None
        if not wheel_state_bounds_match(state.get('area_bounds'), wheel_state_area_bounds(area)):
            self._states.pop(area_key, None)
            return None

        if not wheel_state_center_matches(
            state.get('center_x'),
            state.get('center_y'),
            center_x,
            center_y,
        ):
            self._states.pop(area_key, None)
            return None

        wheel_radius = _float_value(wheel_radius)
        if wheel_state_radius_mismatch(state.get('wheel_radius'), wheel_radius):
            state = dict(state)
            state['wheel_radius_mismatch'] = True
            state['requested_wheel_radius'] = wheel_radius
            return state

        return dict(state)

    def update(
        self,
        area_key,
        area=None,
        center_x=None,
        center_y=None,
        visual_center_x=None,
        visual_center_y=None,
        wheel_radius=None,
        visual_radius=None,
        effective_max_radius=_MISSING,
        outer_control_radius=_MISSING,
        last_detected_handle=None,
        source=None,
    ):
        if not area_key:
            return None

        current = self.get(area_key, area, center_x, center_y) or {}
        current['area_key'] = area_key
        current['area_bounds'] = wheel_state_area_bounds(area)
        current['geometry_signature'] = wheel_state_geometry_signature(area, center_x, center_y)

        center_x = _float_value(center_x)
        center_y = _float_value(center_y)
        visual_center_x = _float_value(visual_center_x)
        visual_center_y = _float_value(visual_center_y)
        wheel_radius = _float_value(wheel_radius)
        visual_radius = _float_value(visual_radius)
        if center_x is not None:
            current['center_x'] = center_x
        if center_y is not None:
            current['center_y'] = center_y
        if visual_center_x is not None:
            current['visual_center_x'] = visual_center_x
        if visual_center_y is not None:
            current['visual_center_y'] = visual_center_y
        if wheel_radius is not None:
            current['wheel_radius'] = wheel_radius
        if visual_radius is not None:
            current['visual_radius'] = visual_radius

        if effective_max_radius is not _MISSING:
            value = should_store_effective_max_radius(effective_max_radius)
            if value is not None:
                current['effective_max_radius'] = value
        if outer_control_radius is not _MISSING:
            value = should_store_outer_control_radius(
                outer_control_radius,
                current.get('outer_control_radius'),
            )
            if value is not None:
                current['outer_control_radius'] = value
        detected = wheel_last_detected_handle_snapshot(last_detected_handle)
        if detected is not None:
            current['last_detected_handle'] = detected
        if source:
            current['source'] = source
        current['updated_at'] = time.time()

        self._states[area_key] = current
        return dict(current)


__all__ = ['WheelStateStore']
