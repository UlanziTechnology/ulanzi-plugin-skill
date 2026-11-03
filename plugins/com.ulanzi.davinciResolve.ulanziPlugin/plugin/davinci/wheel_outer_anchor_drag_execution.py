"""Mouse drag execution for outer-anchor wheel rotation gestures."""

import math
import time

from .config import (
    WHEEL_ANCHOR_DRAG_DURATION_SECONDS,
    WHEEL_ANCHOR_FEEDBACK_SETTLE_SECONDS,
    WHEEL_ORBIT_TARGET_MAX_DURATION_SECONDS,
)
from .wheel_outer_anchor_logic import outer_anchor_drag_plan
from .wheel_outer_anchor_logs import wheel_outer_anchor_drag_log_message


def wheel_outer_anchor_execute_drag(
    area,
    area_name,
    ticks,
    source,
    start_x,
    start_y,
    start_angle,
    state_angle,
    delta_angle,
    handle_radius,
    actual_radius,
    no_progress_count,
    visual_radius,
    outer_control_radius,
    target_x,
    target_y,
    outer_x,
    outer_y,
    mouse_drag_begin_fn,
    mouse_drag_move_absolute_path_fn,
    mouse_drag_end_fn,
    get_cursor_position_fn,
    detect_handle_raw_for_area_fn,
    sensitivity,
    set_cursor_position_fn=None,
    debug_slow_fn=None,
):
    moved = False
    cursor_end_x, cursor_end_y = start_x, start_y
    feedback_handle = None
    near_center_anchor = False
    if handle_radius >= 1.0:
        press_x, press_y = start_x, start_y
        drag_plan = outer_anchor_drag_plan(
            start_x,
            start_y,
            start_angle,
            ticks,
            sensitivity,
            handle_radius,
            actual_radius,
            no_progress_count,
        )
        handle_path = drag_plan['handle_path']
        tangent_dx = drag_plan['tangent_dx']
        tangent_dy = drag_plan['tangent_dy']
        tangent_distance = drag_plan['tangent_distance']
        near_center_anchor = drag_plan['near_center_anchor']
        radial_pull_px = drag_plan['radial_pull_px']
        tangent_radius_scale = drag_plan['tangent_radius_scale']
        if not mouse_drag_begin_fn(press_x, press_y):
            return {'ok': False}
        try:
            print(wheel_outer_anchor_drag_log_message(
                area_name,
                source,
                state_angle,
                delta_angle,
                handle_radius,
                actual_radius,
                near_center_anchor,
                radial_pull_px,
                no_progress_count,
                visual_radius,
                outer_control_radius,
                target_x,
                target_y,
                outer_x,
                outer_y,
                tangent_dx,
                tangent_dy,
                tangent_distance,
                tangent_radius_scale,
                start_x,
                start_y,
                press_x,
                press_y,
                len(handle_path),
            ))
            moved = mouse_drag_move_absolute_path_fn(
                handle_path,
                duration=min(
                    WHEEL_ORBIT_TARGET_MAX_DURATION_SECONDS,
                    WHEEL_ANCHOR_DRAG_DURATION_SECONDS * max(1, abs(ticks)),
                ),
            )
            cursor_end_x, cursor_end_y = get_cursor_position_fn()
        finally:
            mouse_drag_end_fn(cursor_end_x, cursor_end_y, pre_delay=0.0, post_delay=0.0)
        if set_cursor_position_fn:
            set_cursor_position_fn(int(round(target_x)), int(round(target_y)))
        time.sleep(WHEEL_ANCHOR_FEEDBACK_SETTLE_SECONDS)
        feedback_handle = detect_handle_raw_for_area_fn(
            area,
            expected_handle={'x': target_x, 'y': target_y},
        )
    else:
        near_center_anchor = True
        if debug_slow_fn:
            debug_slow_fn(
                f"outer-anchor visual only {area_name} "
                f"angle={math.degrees(state_angle):.1f} radius={handle_radius:.1f}"
            )
        moved = True

    return {
        'ok': True,
        'moved': moved,
        'cursor_end_x': cursor_end_x,
        'cursor_end_y': cursor_end_y,
        'feedback_handle': feedback_handle,
        'near_center_anchor': near_center_anchor,
    }


__all__ = ['wheel_outer_anchor_execute_drag']
