"""Manual mouse drag handling for DaVinci wheel handles."""

from .area_target_helpers import wheel_area_at_point
from .wheel_manual_drag_begin import (
    begin_manual_wheel_drag,
    begin_manual_wheel_drag_immediate,
)
from .wheel_manual_drag_end import end_manual_wheel_drag


def handle_manual_wheel_drag_button_change(
    manager,
    is_down,
    mouse_x,
    mouse_y,
    *,
    plugin_mouse_button_active_fn,
    ready_for_interaction_fn,
    begin_manual_drag_fn,
    end_manual_drag_fn,
    state_callbacks,
    debug_slow_fn=None,
):
    if plugin_mouse_button_active_fn():
        if debug_slow_fn:
            debug_slow_fn(
                f"manual wheel drag ignored plugin mouse "
                f"state={'down' if is_down else 'up'} mouse=({mouse_x:.0f},{mouse_y:.0f})"
            )
        return

    areas = state_callbacks['areas_fn']()
    if not ready_for_interaction_fn() or not areas:
        if not is_down and state_callbacks['manual_drag_state_fn']():
            state_callbacks['clear_manual_drag_state_fn']()
        if debug_slow_fn:
            debug_slow_fn(
                f"manual wheel drag ignored inactive "
                f"state={'down' if is_down else 'up'} mouse=({mouse_x:.0f},{mouse_y:.0f}) "
                f"areas={len(areas)}"
            )
        return

    if is_down:
        if state_callbacks['manual_drag_state_fn']():
            return
        if state_callbacks['param_drag_state_fn']() or state_callbacks['wheel_drag_state_fn']():
            return
        orbit = state_callbacks['wheel_orbit_state_fn']()
        if orbit and orbit.get('dragging'):
            return
        area = wheel_area_at_point(areas, mouse_x, mouse_y)
        if area:
            begin_manual_drag_fn(area, mouse_x, mouse_y)
        elif debug_slow_fn:
            debug_slow_fn(
                f"manual wheel drag ignored outside wheel "
                f"mouse=({mouse_x:.0f},{mouse_y:.0f})"
            )
        return

    if state_callbacks['manual_drag_state_fn']():
        end_manual_drag_fn(mouse_x, mouse_y)


__all__ = [
    'begin_manual_wheel_drag',
    'begin_manual_wheel_drag_immediate',
    'end_manual_wheel_drag',
    'handle_manual_wheel_drag_button_change',
]
