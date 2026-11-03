"""Log message helpers for outer-anchor wheel rotation."""

import math


def _format_degrees(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 'n/a'
    if not math.isfinite(value):
        return 'n/a'
    return f"{math.degrees(value):.1f}"


def _format_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 'n/a'
    if not math.isfinite(value):
        return 'n/a'
    return f"{value:.1f}"


def wheel_outer_anchor_drag_log_message(
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
    step_count,
):
    return (
        f"adjust {area_name}: outer-anchor source={source} "
        f"angle={math.degrees(state_angle):.1f} "
        f"delta={math.degrees(delta_angle):.1f} "
        f"handle_radius={handle_radius:.1f} actual_radius={actual_radius:.1f} "
        f"near_center={near_center_anchor} "
        f"radial_pull={radial_pull_px:.1f} "
        f"stuck={no_progress_count} "
        f"visual_radius={visual_radius:.1f} "
        f"outer_radius={outer_control_radius:.1f} "
        f"target=({target_x:.0f}, {target_y:.0f}) "
        f"outer=({outer_x:.0f}, {outer_y:.0f}) "
        f"tangent=({tangent_dx:.1f}, {tangent_dy:.1f}) "
        f"tangent_distance={tangent_distance:.1f} "
        f"radius_scale={tangent_radius_scale:.2f} "
        f"from=({start_x:.0f}, {start_y:.0f}) "
        f"press=({press_x:.0f}, {press_y:.0f}) "
        f"steps={step_count}"
    )


def wheel_outer_anchor_no_progress_log_message(
    area_name,
    requested_angle_delta,
    feedback_angle_delta,
    next_no_progress_count,
    force_fresh_handle=False,
):
    message = (
        f"outer-anchor no progress {area_name}: "
        f"requested={math.degrees(requested_angle_delta):.1f} "
        f"feedback_delta={math.degrees(feedback_angle_delta):.1f} "
        f"stuck={next_no_progress_count}"
    )
    if force_fresh_handle:
        message += " action=force-fresh-next"
    return message


def wheel_outer_anchor_ignored_feedback_log_message(
    area_name,
    state_angle,
    feedback_angle,
    feedback_angle_error,
    feedback_angle_limit_degrees,
    feedback_radius,
    feedback_radius_delta=None,
    reject_reason=None,
    force_fresh_handle=False,
):
    message = (
        f"outer-anchor ignored feedback {area_name}: "
        f"target_angle={_format_degrees(state_angle)} "
        f"feedback_angle={_format_degrees(feedback_angle)} "
        f"error={_format_degrees(feedback_angle_error)} "
        f"limit={_format_float(feedback_angle_limit_degrees)} "
        f"radius={_format_float(feedback_radius)}"
    )
    if feedback_radius_delta is not None:
        message += f" radius_delta={_format_float(feedback_radius_delta)}"
    if reject_reason:
        message += f" reason={reject_reason}"
    if force_fresh_handle:
        message += " action=force-fresh-next"
    return message


__all__ = [
    'wheel_outer_anchor_drag_log_message',
    'wheel_outer_anchor_ignored_feedback_log_message',
    'wheel_outer_anchor_no_progress_log_message',
]
