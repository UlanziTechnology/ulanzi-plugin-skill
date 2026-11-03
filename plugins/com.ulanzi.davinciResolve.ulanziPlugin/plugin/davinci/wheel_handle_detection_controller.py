"""Manager-level handle detection orchestration for wheel controls."""

import math
import time

from .config import WHEEL_HANDLE_CACHE_SECONDS, WHEEL_HANDLE_STATE_PRESERVE_PX
from .wheel_handle_raw_detection import detect_handle_raw_for_manager_area


def detect_handle_for_manager(
    area_name,
    *,
    state_callbacks,
    detect_wheel_circle_in_area_fn,
    detect_handle_in_area_fn,
    is_davinci_ready_for_interaction_fn,
    clear_hover_state_fn,
    davinci_running_fn,
    debug_slow_fn=None,
):
    """
    Detect the visible white wheel handle and commit it into shared wheel state.

    The pixel classifier still lives near screen capture code; this layer owns
    the manager-facing policy: app readiness, cache preservation, and state
    commit.
    """
    if not is_davinci_ready_for_interaction_fn():
        clear_hover_state_fn(clear_areas=not davinci_running_fn())
        return None

    area = next((item for item in state_callbacks['areas_fn']() if item['name'] == area_name), None)
    if not area:
        return None

    previous = state_callbacks['wheel_handle_for_area_fn'](area_name, {})
    preserve_previous_state = (
        previous
        and time.time() - previous.get('updated_at', 0) <= WHEEL_HANDLE_CACHE_SECONDS
    )
    wheel_geometry = detect_wheel_circle_in_area_fn(area)
    handle = detect_handle_in_area_fn(
        area['x'],
        area['y'],
        area['w'],
        area['h'],
        wheel_geometry,
    )
    if handle:
        if wheel_geometry:
            handle.update(wheel_geometry)
            if debug_slow_fn:
                debug_slow_fn(
                    f"wheel geometry {area_name} "
                    f"center=({wheel_geometry['wheel_center_x']:.0f},{wheel_geometry['wheel_center_y']:.0f}) "
                    f"radius={wheel_geometry['wheel_radius']:.0f}"
                )
        if preserve_previous_state:
            predicted_distance = math.hypot(
                handle['x'] - previous.get('x', handle['x']),
                handle['y'] - previous.get('y', handle['y']),
            )
            preserve_previous_state = predicted_distance <= WHEEL_HANDLE_STATE_PRESERVE_PX
        for key in ('angle', 'radial_axis_angle', 'signed_radius', 'radius'):
            if preserve_previous_state and key in previous:
                handle[key] = previous[key]
        handle['state_preserved'] = bool(preserve_previous_state)
        handle = state_callbacks['commit_wheel_detected_handle_fn'](
            area,
            handle,
            area_name=area_name,
            updated_at=time.time(),
        )
        print(f"检测到 {area_name} 调节点: ({handle['x']:.0f}, {handle['y']:.0f})")

    return handle

__all__ = [
    'detect_handle_for_manager',
    'detect_handle_raw_for_manager_area',
]
