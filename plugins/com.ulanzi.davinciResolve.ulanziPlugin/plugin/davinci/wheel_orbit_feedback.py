"""Closed-loop feedback correction for wheel orbit drag sessions."""

import math
import time

from .config import (
    WHEEL_ORBIT_FEEDBACK_DURATION_SECONDS,
    WHEEL_ORBIT_FEEDBACK_MAX_MOVE_PX,
    WHEEL_ORBIT_FEEDBACK_PASSES,
    WHEEL_ORBIT_FEEDBACK_POSITION_GAIN,
    WHEEL_ORBIT_FEEDBACK_SETTLE_SECONDS,
    WHEEL_ORBIT_FEEDBACK_STEP_PX,
    WHEEL_ORBIT_FEEDBACK_TOLERANCE_PX,
)
from .wheel_orbit_logs import wheel_orbit_feedback_log_message


def apply_wheel_orbit_feedback(
    area,
    area_name,
    target_x,
    target_y,
    mouse_drag_move_by_path_fn,
    detect_handle_raw_for_area_fn,
):
    moved = False
    last_handle = None
    for pass_index in range(WHEEL_ORBIT_FEEDBACK_PASSES):
        time.sleep(WHEEL_ORBIT_FEEDBACK_SETTLE_SECONDS)
        handle = detect_handle_raw_for_area_fn(area)
        if not handle:
            break

        last_handle = handle
        error_x = target_x - handle['x']
        error_y = target_y - handle['y']
        error_distance = math.hypot(error_x, error_y)
        if error_distance <= WHEEL_ORBIT_FEEDBACK_TOLERANCE_PX:
            break

        move_x = error_x * WHEEL_ORBIT_FEEDBACK_POSITION_GAIN
        move_y = error_y * WHEEL_ORBIT_FEEDBACK_POSITION_GAIN
        move_distance = math.hypot(move_x, move_y)
        if move_distance > WHEEL_ORBIT_FEEDBACK_MAX_MOVE_PX:
            scale = WHEEL_ORBIT_FEEDBACK_MAX_MOVE_PX / move_distance
            move_x *= scale
            move_y *= scale
            move_distance = WHEEL_ORBIT_FEEDBACK_MAX_MOVE_PX

        steps = max(2, int(math.ceil(move_distance / WHEEL_ORBIT_FEEDBACK_STEP_PX)))
        print(wheel_orbit_feedback_log_message(
            area_name,
            pass_index,
            error_x,
            error_y,
            move_x,
            move_y,
            error_distance,
        ))
        moved = mouse_drag_move_by_path_fn(
            move_x,
            move_y,
            steps=steps,
            duration=WHEEL_ORBIT_FEEDBACK_DURATION_SECONDS,
        ) or moved

    return moved, last_handle


__all__ = ['apply_wheel_orbit_feedback']
