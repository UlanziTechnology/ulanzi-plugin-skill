"""Manual wheel-drag release handling."""

import math
import time

from .area_target_helpers import area_label
from .config import WHEEL_MANUAL_DRAG_RELEASE_SETTLE_SECONDS
from .wheel_manual_overlay_controller import restore_manual_wheel_drag_overlay


def end_manual_wheel_drag(
    manager,
    mouse_x,
    mouse_y,
    *,
    detect_handle_raw_for_area_fn,
    state_callbacks,
    debug_slow_fn=None,
):
    drag = state_callbacks['manual_drag_state_fn']()
    if not drag:
        return False

    state_callbacks['clear_manual_drag_state_fn']()
    area = drag.get('area')
    key = drag.get('key')
    if not area or not key:
        return False

    if WHEEL_MANUAL_DRAG_RELEASE_SETTLE_SECONDS > 0:
        time.sleep(WHEEL_MANUAL_DRAG_RELEASE_SETTLE_SECONDS)

    state_callbacks['clear_control_state_fn'](
        clear_target_lock=True,
        clear_segment=True,
        clear_anchor=True,
        clear_diameter=True,
    )
    handle = detect_handle_raw_for_area_fn(area)
    stored = state_callbacks['store_wheel_handle_from_detection_fn'](
        area,
        handle,
        source='manual_release',
    )
    if stored:
        state_callbacks['mark_recent_wheel_area_fn'](area)

    state_callbacks['set_current_hover_area_fn'](area)
    restore_manual_wheel_drag_overlay(manager, area, key)

    if debug_slow_fn:
        if handle:
            center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
            center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
            radius = math.hypot(float(handle['x']) - float(center_x), float(handle['y']) - float(center_y))
            debug_slow_fn(
                f"manual wheel drag end {area_label(area)} "
                f"mouse=({mouse_x:.0f},{mouse_y:.0f}) "
                f"handle=({handle['x']:.0f},{handle['y']:.0f}) radius={radius:.1f}"
            )
        else:
            debug_slow_fn(
                f"manual wheel drag end {area_label(area)} "
                f"mouse=({mouse_x:.0f},{mouse_y:.0f}) handle=missing"
            )
    return stored


__all__ = ['end_manual_wheel_drag']
