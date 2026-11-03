"""Log message helpers for closed-loop wheel orbit sessions."""

import math


def wheel_orbit_motion_log_message(
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
    step_count,
):
    return (
        f"adjust {area_name}: orbit short-arc source={source} "
        f"angle={math.degrees(target_angle):.1f} "
        f"base_delta={math.degrees(base_delta_angle):.1f} "
        f"delta={math.degrees(delta_angle):.1f} "
        f"radius={locked_radius:.0f} actual_radius={actual_radius:.0f} "
        f"target=({target_x:.0f}, {target_y:.0f}) "
        f"from=({start_x:.0f}, {start_y:.0f}) "
        f"mouse_from=({start_mouse_x:.0f}, {start_mouse_y:.0f}) "
        f"press=({start_mouse_x:.0f}, {start_mouse_y:.0f}) "
        f"steps={step_count}"
    )


def wheel_orbit_feedback_log_message(
    area_name,
    pass_index,
    error_x,
    error_y,
    move_x,
    move_y,
    error_distance,
):
    return (
        f"feedback {area_name}: pass={pass_index + 1} "
        f"error=({error_x:.1f}, {error_y:.1f}) "
        f"move=({move_x:.1f}, {move_y:.1f}) "
        f"distance={error_distance:.1f}"
    )


__all__ = [
    'wheel_orbit_feedback_log_message',
    'wheel_orbit_motion_log_message',
]
