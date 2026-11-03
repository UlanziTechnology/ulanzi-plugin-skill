"""Release handling for non-orbit wheel dial drags."""

import time

from .config import WHEEL_DIAL_DRAG_IDLE_SECONDS


def release_wheel_drag(
    state_callbacks,
    mouse_drag_end_fn,
    *,
    set_cursor_position_fn=None,
    debug_slow_fn=None,
):
    drag = state_callbacks['wheel_drag_state_fn']()
    if not drag:
        return False

    state_callbacks['clear_wheel_drag_state_fn']()
    if drag.get('button_down', True):
        drag['button_down'] = False
        mouse_drag_end_fn(drag['x'], drag['y'])
    restore_x = drag.get('predicted_handle_x')
    restore_y = drag.get('predicted_handle_y')
    if restore_x is not None and restore_y is not None and set_cursor_position_fn:
        set_cursor_position_fn(int(round(restore_x)), int(round(restore_y)))
    if debug_slow_fn:
        debug_slow_fn(f"wheel drag release {drag['name']} at=({drag['x']:.0f},{drag['y']:.0f})")
    return True


def release_wheel_drag_if_idle(state_callbacks, release_wheel_drag_fn):
    drag = state_callbacks['wheel_drag_state_fn']()
    if not drag:
        return False

    if time.time() - drag['last_at'] >= WHEEL_DIAL_DRAG_IDLE_SECONDS:
        return release_wheel_drag_fn()
    return False


__all__ = [
    'release_wheel_drag',
    'release_wheel_drag_if_idle',
]
