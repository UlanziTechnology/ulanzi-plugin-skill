"""Manual wheel-drag begin handling."""

import time

from .area_target_helpers import area_key, area_label, wheel_area_at_point
from .wheel_manual_overlay_controller import show_manual_wheel_drag_overlay
from .wheel_state_manual_payloads import wheel_manual_drag_payload


def begin_manual_wheel_drag(
    manager,
    area,
    mouse_x,
    mouse_y,
    *,
    overlay_class,
    clear_wheel_orbit_fn,
    release_param_drag_fn,
    release_wheel_drag_fn,
    state_callbacks,
    debug_slow_fn=None,
):
    if not area or area.get('type') != 'wheel':
        return False

    key = area_key(area)
    if not key:
        return False

    backend = getattr(manager, '_smooth_wheel_backend', None)
    invalidate = getattr(backend, 'invalidate_diameter', None)
    if callable(invalidate):
        invalidate('manual_drag_begin')
    clear_wheel_orbit_fn()
    release_param_drag_fn()
    release_wheel_drag_fn()
    state_callbacks['clear_control_state_fn'](
        clear_target_lock=True,
        clear_segment=True,
        clear_anchor=True,
        clear_diameter=True,
    )
    state_callbacks['set_manual_drag_state_fn'](
        wheel_manual_drag_payload(
            area,
            key,
            started_at=time.time(),
        )
    )
    state_callbacks['set_current_hover_area_fn'](area)
    state_callbacks['mark_recent_wheel_area_fn'](area)

    show_manual_wheel_drag_overlay(manager, area, key, overlay_class)
    if debug_slow_fn:
        debug_slow_fn(
            f"manual wheel drag begin {area_label(area)} "
            f"mouse=({mouse_x:.0f},{mouse_y:.0f})"
        )
    return True


def begin_manual_wheel_drag_immediate(
    manager,
    is_down,
    mouse_x,
    mouse_y,
    *,
    plugin_mouse_button_active_fn,
    native_overlay_enabled,
    state_callbacks,
    debug_slow_fn=None,
):
    if not is_down:
        return False
    if plugin_mouse_button_active_fn():
        return False
    if not native_overlay_enabled:
        return False
    areas = state_callbacks['areas_fn']()
    if not (state_callbacks['davinci_ready_flags_fn']() and areas):
        return False
    if (
        state_callbacks['manual_drag_state_fn']()
        or state_callbacks['param_drag_state_fn']()
        or state_callbacks['wheel_drag_state_fn']()
    ):
        return False
    orbit = state_callbacks['wheel_orbit_state_fn']()
    if orbit and orbit.get('dragging'):
        return False

    area = wheel_area_at_point(areas, mouse_x, mouse_y)
    if not area:
        return False

    key = area_key(area)
    if not key:
        return False

    backend = getattr(manager, '_smooth_wheel_backend', None)
    invalidate = getattr(backend, 'invalidate_diameter', None)
    if callable(invalidate):
        invalidate('manual_drag_begin')
    state_callbacks['clear_control_state_fn'](
        clear_target_lock=True,
        clear_segment=True,
        clear_anchor=True,
        clear_diameter=True,
    )
    state_callbacks['set_manual_drag_state_fn'](
        wheel_manual_drag_payload(
            area,
            key,
            immediate=True,
            started_at=time.time(),
        )
    )
    state_callbacks['set_current_hover_area_fn'](area)
    state_callbacks['mark_recent_wheel_area_fn'](area)
    state_callbacks['clear_pending_hover_overlay_fn']()

    overlay = state_callbacks['overlay_for_key_fn'](key)
    if overlay:
        overlay.hide_for_manual_drag_immediate()
        state_callbacks['set_hover_visible_key_fn'](key)
        if debug_slow_fn:
            debug_slow_fn(
                f"manual wheel drag immediate dot hide {area_label(area)} "
                f"mouse=({mouse_x:.0f},{mouse_y:.0f})"
            )
        return True

    if debug_slow_fn:
        debug_slow_fn(
            f"manual wheel drag immediate armed {area_label(area)} "
            f"mouse=({mouse_x:.0f},{mouse_y:.0f}) overlay=missing"
        )
    return True


__all__ = [
    'begin_manual_wheel_drag',
    'begin_manual_wheel_drag_immediate',
]
