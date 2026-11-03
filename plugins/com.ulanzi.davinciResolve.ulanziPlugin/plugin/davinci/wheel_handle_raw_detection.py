"""Raw wheel-handle detection that does not mutate shared state."""

import time

from .wheel_state_handle_payloads import wheel_handle_timestamp_payload


def detect_handle_raw_for_manager_area(
    area,
    *,
    detect_wheel_circle_in_area_fn,
    detect_handle_in_area_fn,
    is_davinci_ready_for_interaction_fn,
    expected_handle=None,
    expected_axis=None,
):
    """Detect a wheel handle without mutating shared manager state."""
    if not is_davinci_ready_for_interaction_fn() or not area:
        return None

    wheel_geometry = detect_wheel_circle_in_area_fn(area)
    handle = detect_handle_in_area_fn(
        area['x'],
        area['y'],
        area['w'],
        area['h'],
        wheel_geometry,
        expected_handle,
        expected_axis,
    )
    if handle:
        if wheel_geometry:
            handle.update(wheel_geometry)
        handle = wheel_handle_timestamp_payload(handle, updated_at=time.time())
    return handle


__all__ = ['detect_handle_raw_for_manager_area']
