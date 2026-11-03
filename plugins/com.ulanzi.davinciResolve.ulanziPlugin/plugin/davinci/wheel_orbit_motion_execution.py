"""Mouse motion execution for wheel orbit drag sessions."""

from .config import (
    WHEEL_ORBIT_TARGET_DURATION_SECONDS,
    WHEEL_ORBIT_TARGET_MAX_DURATION_SECONDS,
)
from .wheel_orbit_feedback import apply_wheel_orbit_feedback
from .wheel_orbit_logs import wheel_orbit_motion_log_message


def wheel_orbit_execute_motion(
    area,
    area_name,
    target_key,
    ticks,
    orbit_context,
    orbit_plan,
    mouse_drag_move_path_fn,
    mouse_drag_move_by_path_fn,
    get_cursor_position_fn,
    detect_handle_raw_for_area_fn,
    release_wheel_orbit_drag_fn,
    orbit_state_fn,
    update_orbit_motion_done_fn,
):
    source = orbit_context['source']
    start_x = orbit_context['start_x']
    start_y = orbit_context['start_y']
    start_mouse_x = orbit_context['start_mouse_x']
    start_mouse_y = orbit_context['start_mouse_y']
    locked_radius = orbit_context['locked_radius']
    actual_radius = orbit_context['actual_radius']
    target_angle = orbit_plan['target_angle']
    target_x = orbit_plan['target_x']
    target_y = orbit_plan['target_y']
    base_delta_angle = orbit_plan['base_delta_angle']
    delta_angle = orbit_plan['delta_angle']
    handle_path = orbit_plan['handle_path']

    moved = False
    cursor_end_x, cursor_end_y = start_mouse_x, start_mouse_y
    feedback_handle = None
    try:
        print(wheel_orbit_motion_log_message(
            area_name,
            source,
            target_angle,
            base_delta_angle,
            delta_angle,
            locked_radius,
            actual_radius,
            target_x,
            target_y,
            start_x,
            start_y,
            start_mouse_x,
            start_mouse_y,
            max(0, len(handle_path) - 1),
        ))
        moved = mouse_drag_move_path_fn(
            handle_path[1:],
            duration=min(
                WHEEL_ORBIT_TARGET_MAX_DURATION_SECONDS,
                WHEEL_ORBIT_TARGET_DURATION_SECONDS * max(1, abs(ticks)),
            ),
        )
        feedback_moved, feedback_handle = apply_wheel_orbit_feedback(
            area,
            area_name,
            target_x,
            target_y,
            mouse_drag_move_by_path_fn,
            detect_handle_raw_for_area_fn,
        )
        moved = feedback_moved or moved
        cursor_end_x, cursor_end_y = get_cursor_position_fn()
    except Exception:
        release_wheel_orbit_drag_fn()
        raise
    finally:
        orbit = orbit_state_fn()
        if orbit and orbit.get('target_key') == target_key:
            update_orbit_motion_done_fn()

    return {
        'moved': moved,
        'cursor_end_x': cursor_end_x,
        'cursor_end_y': cursor_end_y,
        'feedback_handle': feedback_handle,
    }


__all__ = ['wheel_orbit_execute_motion']
