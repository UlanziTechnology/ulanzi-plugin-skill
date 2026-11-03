"""Dial-driven numeric and slider parameter dragging."""

import math
import threading
import time

from .area_target_helpers import area_key
from .config import (
    CONTINUOUS_PARAM_DRAG_TYPES,
    NUMERIC_DIAL_PIXELS_PER_TICK,
    PARAM_DIAL_DRAG_IDLE_SECONDS,
    PARAM_DIAL_DRAG_USER_MOVE_GRACE_SECONDS,
    PARAM_DIAL_DRAG_USER_MOVE_RELEASE_PX,
    PARAM_DIAL_PRESS_SETTLE_SECONDS,
    PARAM_DIAL_RESTORE_CURSOR_AFTER_UP_SECONDS,
    PARAM_DIAL_RESTORE_CURSOR_MAX_DRIFT_PX,
    SLIDER_DIAL_PIXELS_PER_TICK,
    VERTICAL_SLIDER_DIAL_PIXELS_PER_TICK,
)


def param_drag_start_point(area, detect_vertical_slider_handle_fn):
    source_frame = area.get('source_frame')
    if area.get('type') == 'numeric' and source_frame:
        x, y, w, h = source_frame
        return x + w / 2, y + h / 2
    if area.get('type') == 'vertical_slider':
        handle = detect_vertical_slider_handle_fn(area)
        if handle:
            return handle['x'], handle['y']
        if source_frame:
            x, y, w, h = source_frame
            return x + w / 2, y + h / 2
    return area['center_x'], area['center_y']


def cancel_param_release_timer(manager):
    timer = manager._param_release_timer
    manager._param_release_timer = None
    if timer:
        timer.cancel()


def schedule_param_release_timer(manager, release_callback, delay=None):
    cancel_param_release_timer(manager)
    release_delay = PARAM_DIAL_DRAG_IDLE_SECONDS if delay is None else max(0.01, delay)
    timer = threading.Timer(release_delay, release_callback)
    timer.daemon = True
    manager._param_release_timer = timer
    timer.start()


def release_param_drag(
    manager,
    restore_cursor,
    mouse_drag_end_fn,
    set_cursor_position_fn=None,
    debug_slow_fn=None,
):
    if not manager._param_drag:
        return False

    drag = manager._param_drag
    manager._param_drag = None
    cancel_param_release_timer(manager)
    mouse_drag_end_fn(drag['x'], drag['y'], pre_delay=0.0, post_delay=0.0)
    restore_x = drag.get('restore_x')
    restore_y = drag.get('restore_y')
    if restore_cursor and restore_x is not None and restore_y is not None and set_cursor_position_fn:
        if PARAM_DIAL_RESTORE_CURSOR_AFTER_UP_SECONDS > 0:
            time.sleep(PARAM_DIAL_RESTORE_CURSOR_AFTER_UP_SECONDS)
        set_cursor_position_fn(int(round(restore_x)), int(round(restore_y)))
    if debug_slow_fn:
        debug_slow_fn(
            f"param drag release {drag['name']} "
            f"at=({drag['x']:.0f},{drag['y']:.0f}) restore={bool(restore_cursor)}"
        )
    return True


def should_restore_param_drag_cursor(manager, drag, get_cursor_position_fn):
    if not drag:
        return False
    if drag.get('restore_x') is None or drag.get('restore_y') is None:
        return False
    if not get_cursor_position_fn:
        return False

    cursor_x, cursor_y = get_cursor_position_fn()
    distance = math.hypot(
        cursor_x - drag.get('x', cursor_x),
        cursor_y - drag.get('y', cursor_y),
    )
    return distance <= PARAM_DIAL_RESTORE_CURSOR_MAX_DRIFT_PX


def release_param_drag_after_idle(
    manager,
    get_cursor_position_fn,
    mouse_drag_end_fn,
    set_cursor_position_fn=None,
    debug_slow_fn=None,
):
    drag = manager._param_drag
    return release_param_drag(
        manager,
        should_restore_param_drag_cursor(manager, drag, get_cursor_position_fn),
        mouse_drag_end_fn,
        set_cursor_position_fn=set_cursor_position_fn,
        debug_slow_fn=debug_slow_fn,
    )


def release_param_drag_if_idle(
    manager,
    release_after_idle_fn,
    schedule_release_timer_fn,
):
    if not manager._param_drag:
        return False

    idle_seconds = time.time() - max(
        manager._param_drag['last_at'],
        manager._last_param_dial_activity_at,
    )
    if idle_seconds >= PARAM_DIAL_DRAG_IDLE_SECONDS:
        return release_after_idle_fn()

    schedule_release_timer_fn(PARAM_DIAL_DRAG_IDLE_SECONDS - idle_seconds)
    return False


def release_param_drag_if_cursor_moved(
    manager,
    mouse_x,
    mouse_y,
    release_param_drag_fn,
    debug_slow_fn=None,
):
    if not manager._param_drag:
        return False

    drag = manager._param_drag
    if time.time() - drag['last_at'] < PARAM_DIAL_DRAG_USER_MOVE_GRACE_SECONDS:
        return False

    distance = math.hypot(mouse_x - drag['x'], mouse_y - drag['y'])
    if distance >= PARAM_DIAL_DRAG_USER_MOVE_RELEASE_PX:
        if debug_slow_fn:
            debug_slow_fn(
                f"param drag release by cursor move {drag['name']} "
                f"cursor=({mouse_x:.0f},{mouse_y:.0f}) "
                f"expected=({drag['x']:.0f},{drag['y']:.0f}) "
                f"distance={distance:.1f}"
            )
        return release_param_drag_fn(restore_cursor=False)
    return False


def move_param_drag(
    manager,
    ticks,
    mouse_drag_move_by_fn,
    mouse_drag_move_fn,
    note_param_dial_activity_fn=None,
    schedule_param_release_timer_fn=None,
):
    if not manager._param_drag or ticks == 0:
        return False

    drag = manager._param_drag
    target_type = drag['target_type']
    if target_type == 'numeric':
        pixels_per_tick = NUMERIC_DIAL_PIXELS_PER_TICK
    elif target_type == 'vertical_slider':
        pixels_per_tick = VERTICAL_SLIDER_DIAL_PIXELS_PER_TICK
    else:
        pixels_per_tick = SLIDER_DIAL_PIXELS_PER_TICK

    if target_type == 'numeric':
        residue_key = drag.get('target_key')
        if manager._param_dial_residue_key != residue_key:
            manager._param_dial_residue_key = residue_key
            manager._param_dial_pixel_residue = 0.0
        desired_delta = ticks * manager.sensitivity * pixels_per_tick + manager._param_dial_pixel_residue
        delta = math.floor(desired_delta) if desired_delta >= 0 else math.ceil(desired_delta)
        manager._param_dial_pixel_residue = desired_delta - delta
        delta_x = delta
        delta_y = 0
    elif target_type == 'vertical_slider':
        delta_x = 0
        delta_y = -ticks * manager.sensitivity * pixels_per_tick
    else:
        delta_x = ticks * manager.sensitivity * pixels_per_tick
        delta_y = 0

    drag['x'] += delta_x
    drag['y'] += delta_y
    drag['last_at'] = time.time()
    if target_type in CONTINUOUS_PARAM_DRAG_TYPES and note_param_dial_activity_fn:
        note_param_dial_activity_fn()
    if (delta_x or delta_y) and not mouse_drag_move_by_fn(delta_x, delta_y):
        mouse_drag_move_fn(drag['x'], drag['y'])
    if target_type in CONTINUOUS_PARAM_DRAG_TYPES and schedule_param_release_timer_fn:
        schedule_param_release_timer_fn()
    print(f"param adjust {drag['name']}: move=({drag['x']:.0f}, {drag['y']:.0f})")
    return True


def handle_param_dial_drag(
    manager,
    area,
    ticks,
    get_cursor_position_fn,
    mouse_drag_begin_fn,
    mouse_drag_move_by_fn,
    mouse_drag_move_fn,
    detect_vertical_slider_handle_fn,
    release_param_drag_fn,
    lock_hover_for_param_dial_fn,
    note_param_dial_activity_fn,
    schedule_param_release_timer_fn,
    debug_slow_fn=None,
):
    if ticks == 0:
        return False

    target_key = area_key(area)
    if not target_key:
        return False

    if (
        not manager._param_drag
        or manager._param_drag['target_key'] != target_key
    ):
        release_param_drag_fn()
        restore_x, restore_y = get_cursor_position_fn()
        lock_hover_for_param_dial_fn()
        start_x, start_y = param_drag_start_point(area, detect_vertical_slider_handle_fn)
        if not mouse_drag_begin_fn(start_x, start_y):
            return False
        target_type = area.get('type')
        if target_type in CONTINUOUS_PARAM_DRAG_TYPES:
            time.sleep(PARAM_DIAL_PRESS_SETTLE_SECONDS)
        manager._param_drag = {
            'target_key': target_key,
            'target_type': target_type,
            'name': area['name'],
            'x': start_x,
            'y': start_y,
            'restore_x': restore_x,
            'restore_y': restore_y,
            'last_at': time.time(),
        }
        if debug_slow_fn:
            debug_slow_fn(
                f"param drag begin {area['name']} "
                f"mode={area.get('drag_mode', 'default')} "
                f"at=({start_x:.0f},{start_y:.0f})"
            )

    lock_hover_for_param_dial_fn()
    if area.get('type') in CONTINUOUS_PARAM_DRAG_TYPES:
        note_param_dial_activity_fn()
    moved = move_param_drag(
        manager,
        ticks,
        mouse_drag_move_by_fn,
        mouse_drag_move_fn,
        note_param_dial_activity_fn=note_param_dial_activity_fn,
        schedule_param_release_timer_fn=schedule_param_release_timer_fn,
    )
    if area.get('type') not in CONTINUOUS_PARAM_DRAG_TYPES:
        release_param_drag_fn()
    return moved


__all__ = [
    'cancel_param_release_timer',
    'handle_param_dial_drag',
    'move_param_drag',
    'param_drag_start_point',
    'release_param_drag',
    'release_param_drag_after_idle',
    'release_param_drag_if_cursor_moved',
    'release_param_drag_if_idle',
    'schedule_param_release_timer',
    'should_restore_param_drag_cursor',
]
