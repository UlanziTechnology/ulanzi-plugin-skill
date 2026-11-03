"""Release and idle handling for wheel orbit drag sessions."""

import math
import time

from .config import (
    WHEEL_ORBIT_DRAG_IDLE_SECONDS,
    WHEEL_ORBIT_STATE_IDLE_SECONDS,
    WHEEL_ORBIT_USER_MOVE_GRACE_SECONDS,
    WHEEL_ORBIT_USER_MOVE_RELEASE_PX,
)
from .wheel_state_orbit_payloads import wheel_orbit_release_payload


def release_wheel_orbit_drag(
    state_callbacks,
    mouse_drag_end_fn,
    *,
    restore_cursor=True,
    set_cursor_position_fn=None,
    debug_slow_fn=None,
):
    orbit = state_callbacks['wheel_orbit_state_fn']()
    if not orbit or not orbit.get('dragging'):
        return False

    orbit.update(wheel_orbit_release_payload())
    mouse_drag_end_fn(orbit.get('x', 0), orbit.get('y', 0))
    restore_x = orbit.get('handle_x')
    restore_y = orbit.get('handle_y')
    if restore_cursor and restore_x is not None and restore_y is not None and set_cursor_position_fn:
        set_cursor_position_fn(int(round(restore_x)), int(round(restore_y)))
        orbit['x'] = restore_x
        orbit['y'] = restore_y
    if debug_slow_fn:
        debug_slow_fn(
            f"wheel orbit release {orbit.get('name', 'Unknown')} "
            f"at=({orbit.get('x', 0):.0f},{orbit.get('y', 0):.0f})"
        )
    return True


def clear_wheel_orbit(state_callbacks, release_wheel_orbit_drag_fn):
    release_wheel_orbit_drag_fn()
    state_callbacks['clear_wheel_orbit_state_fn']()


def release_wheel_orbit_if_idle(state_callbacks, release_wheel_orbit_drag_fn):
    orbit = state_callbacks['wheel_orbit_state_fn']()
    if not orbit:
        return False

    idle_seconds = time.time() - orbit.get('last_at', 0)
    if orbit.get('dragging') and idle_seconds >= WHEEL_ORBIT_DRAG_IDLE_SECONDS:
        return release_wheel_orbit_drag_fn()
    if not orbit.get('dragging') and idle_seconds >= WHEEL_ORBIT_STATE_IDLE_SECONDS:
        state_callbacks['clear_wheel_orbit_state_fn']()
    return False


def release_wheel_orbit_if_cursor_moved(
    state_callbacks,
    mouse_x,
    mouse_y,
    release_wheel_orbit_drag_fn,
    *,
    debug_slow_fn=None,
):
    orbit = state_callbacks['wheel_orbit_state_fn']()
    if not orbit or not orbit.get('dragging'):
        return False

    if orbit.get('moving'):
        return False

    if time.time() - orbit.get('last_at', 0) < WHEEL_ORBIT_USER_MOVE_GRACE_SECONDS:
        return False

    distance = math.hypot(mouse_x - orbit.get('x', mouse_x), mouse_y - orbit.get('y', mouse_y))
    if distance >= WHEEL_ORBIT_USER_MOVE_RELEASE_PX:
        if debug_slow_fn:
            debug_slow_fn(
                f"wheel orbit release by cursor move {orbit.get('name', 'Unknown')} "
                f"cursor=({mouse_x:.0f},{mouse_y:.0f}) "
                f"expected=({orbit.get('x', 0):.0f},{orbit.get('y', 0):.0f}) "
                f"distance={distance:.1f}"
            )
        return release_wheel_orbit_drag_fn(restore_cursor=False)
    return False


__all__ = [
    'clear_wheel_orbit',
    'release_wheel_orbit_drag',
    'release_wheel_orbit_if_cursor_moved',
    'release_wheel_orbit_if_idle',
]
