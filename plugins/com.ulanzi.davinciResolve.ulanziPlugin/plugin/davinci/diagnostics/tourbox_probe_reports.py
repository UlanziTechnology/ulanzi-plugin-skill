"""Report builders for TourBox diagnostic probes."""

import json
import math
import os


def tourbox_area_snapshot(area):
    return {key: area.get(key) for key in ('name', 'x', 'y', 'w', 'h')}


def tourbox_point_list(points):
    return [[round(x, 3), round(y, 3)] for x, y in points]


def tourbox_radius_target_report(
    *,
    enabled,
    source,
    radius_target,
    handle_radius,
    target_seconds,
    target_reset_px,
    radius_target_before,
    radius_target_after,
    target_now,
):
    return {
        'enabled': enabled,
        'source': source,
        'target_radius_px': round(float(radius_target), 3),
        'target_error_px': round(float(radius_target - handle_radius), 3),
        'seconds': round(target_seconds, 3),
        'manual_reset_px': round(target_reset_px, 3),
        'before': None if not isinstance(radius_target_before, dict) else {
            'target_radius_px': round(
                float(radius_target_before.get('target_radius', handle_radius)),
                3,
            ),
            'last_observed_radius_px': round(
                float(radius_target_before.get('last_observed_radius', handle_radius)),
                3,
            ),
            'age_seconds': round(
                max(
                    0.0,
                    target_now - float(radius_target_before.get('updated_at', target_now)),
                ),
                3,
            ),
        },
        'after': None if not isinstance(radius_target_after, dict) else {
            'target_radius_px': round(
                float(radius_target_after.get('target_radius', radius_target)),
                3,
            ),
            'last_observed_radius_px': round(
                float(radius_target_after.get('last_observed_radius', handle_radius)),
                3,
            ),
        },
    }


def tourbox_offscreen_probe_report(
    *,
    mode,
    wheel_label,
    ticks,
    direction,
    invert_tick_direction,
    extra_info,
    run_dir,
    original_cursor,
    final_cursor_policy,
    final_cursor_target,
    area,
    handle,
    raw_handle,
    handle_source,
    before_suspicion_reason,
    after_handle,
    after_raw_handle,
    after_source,
    after_suspicion_reason,
    predicted_after,
    axis_angle,
    axis_mode,
    axis_source,
    axis_lock_seconds,
    center_bridge_seconds,
    probe_state,
    bridge_info,
    start_signed_axis,
    start_perpendicular_axis,
    handle_radius,
    line_distance_requested_px,
    line_distance_px,
    line_steps,
    guard_info,
    line_points,
    events,
    result_error,
):
    return {
        'mode': mode,
        'wheel': wheel_label,
        'ticks': ticks,
        'direction': direction,
        'invert_tick_direction': invert_tick_direction,
        'extra_info': extra_info,
        'run_dir': run_dir,
        'original_cursor': list(original_cursor),
        'cursor_after_drag': {
            'policy': final_cursor_policy,
            'target': final_cursor_target,
        },
        'area': tourbox_area_snapshot(area),
        'before_handle': handle,
        'before_raw_handle': raw_handle,
        'before_handle_source': handle_source,
        'before_suspicion_reason': before_suspicion_reason,
        'after_handle': after_handle,
        'after_raw_handle': after_raw_handle,
        'after_handle_source': after_source,
        'after_suspicion_reason': after_suspicion_reason,
        'predicted_after_handle': predicted_after,
        'axis_angle_deg': round(math.degrees(axis_angle), 3),
        'axis_mode': axis_mode,
        'axis_source': axis_source,
        'axis_lock_seconds': axis_lock_seconds,
        'center_bridge_seconds': center_bridge_seconds,
        'axis_state_before': probe_state,
        'center_bridge': bridge_info,
        'start_axis_geometry': {
            'signed_px': round(start_signed_axis, 3),
            'perpendicular_px': round(start_perpendicular_axis, 3),
            'handle_radius_px': round(handle_radius, 3),
        },
        'line_distance_requested_px': round(line_distance_requested_px, 3),
        'line_distance_px': round(line_distance_px, 3),
        'line_steps': line_steps,
        'center_guard': guard_info,
        'line_points': tourbox_point_list(line_points),
        'events': events,
        'error': result_error,
    }


def tourbox_orbit_probe_report(
    *,
    mode,
    arc_source,
    wheel_label,
    ticks,
    tick_direction,
    orbit_invert_tick_direction,
    delta_degrees,
    mouse_delta_angle,
    mouse_angle_gain,
    predictive_enabled,
    predictive_start_source,
    predictive_skip_after_detect,
    predictive_count_before,
    predictive_count_after,
    predictive_detect_every,
    predictive_cache_seconds,
    handle_angle_response_gain,
    handle_radius_response_per_tick,
    extra_info,
    run_dir,
    original_cursor,
    final_cursor_policy,
    final_cursor_target,
    area,
    center_x,
    center_y,
    wheel_radius,
    raw_handle,
    after_handle,
    after_raw_handle,
    after_source,
    predicted_after,
    start_angle,
    target_angle,
    handle_radius,
    desired_radius,
    press_source,
    press_x,
    press_y,
    press_radius,
    radius_target_enabled,
    radius_target_source,
    radius_target,
    target_seconds,
    target_reset_px,
    radius_target_before,
    radius_target_after,
    target_now,
    arc_radius,
    arc_end_radius,
    local_radius_bias,
    local_radius_bias_from_radius,
    local_radius_bias_from_error,
    outer_edge_clamp_report,
    arc_steps,
    arc_points,
    events,
    result_error,
):
    return {
        'mode': mode,
        'arc_source': arc_source,
        'wheel': wheel_label,
        'ticks': ticks,
        'tick_direction': tick_direction,
        'orbit_invert_tick_direction': orbit_invert_tick_direction,
        'delta_degrees': round(delta_degrees, 3),
        'mouse_delta_degrees': round(math.degrees(mouse_delta_angle), 3),
        'mouse_angle_gain': mouse_angle_gain,
        'predictive': {
            'enabled': predictive_enabled,
            'start_source': predictive_start_source,
            'skip_after_detect': predictive_skip_after_detect,
            'count_before': predictive_count_before,
            'count_after': predictive_count_after,
            'detect_every': predictive_detect_every,
            'cache_seconds': round(predictive_cache_seconds, 3),
            'handle_angle_response_gain': round(handle_angle_response_gain, 4),
            'handle_radius_response_per_tick_px': round(handle_radius_response_per_tick, 3),
        },
        'extra_info': extra_info,
        'run_dir': run_dir,
        'original_cursor': list(original_cursor),
        'cursor_after_drag': {
            'policy': final_cursor_policy,
            'target': final_cursor_target,
        },
        'area': tourbox_area_snapshot(area),
        'wheel_geometry': {
            'center_x': round(float(center_x), 3),
            'center_y': round(float(center_y), 3),
            'wheel_radius': round(float(wheel_radius), 3),
        },
        'before_handle': raw_handle,
        'after_handle': after_handle,
        'after_raw_handle': after_raw_handle,
        'after_handle_source': after_source,
        'predicted_after_handle': predicted_after,
        'start_angle_deg': round(math.degrees(start_angle), 3),
        'target_angle_deg': round(math.degrees(target_angle), 3),
        'handle_radius_px': round(handle_radius, 3),
        'desired_radius_px': round(desired_radius, 3),
        'press_point': {
            'source': press_source,
            'x': round(press_x, 3),
            'y': round(press_y, 3),
            'radius_px': round(press_radius, 3),
        },
        'radius_target': tourbox_radius_target_report(
            enabled=radius_target_enabled,
            source=radius_target_source,
            radius_target=radius_target,
            handle_radius=handle_radius,
            target_seconds=target_seconds,
            target_reset_px=target_reset_px,
            radius_target_before=radius_target_before,
            radius_target_after=radius_target_after,
            target_now=target_now,
        ),
        'arc_radius_px': round(arc_radius, 3),
        'arc_end_radius_px': round(arc_end_radius, 3),
        'local_radius_bias_px': round(local_radius_bias, 3),
        'local_radius_bias_from_radius_px': round(local_radius_bias_from_radius, 3),
        'local_radius_bias_from_error_px': round(local_radius_bias_from_error, 3),
        'outer_edge_clamp': outer_edge_clamp_report,
        'arc_steps': arc_steps,
        'arc_points': tourbox_point_list(arc_points),
        'events': events,
        'error': result_error,
    }


def write_tourbox_probe_report(run_dir, report):
    report_path = os.path.join(run_dir, 'report.json')
    with open(report_path, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return report_path


def print_tourbox_offscreen_probe_result(mode, wheel_label, handle, after_handle, report_path):
    if after_handle:
        print(
            "tourbox probe "
            f"{mode} {wheel_label} "
            f"handle=({handle['x']:.1f},{handle['y']:.1f})->"
            f"({after_handle['x']:.1f},{after_handle['y']:.1f}) "
            f"report={report_path}"
        )
    else:
        print(f"tourbox probe {mode} finished without after-handle report={report_path}")


def print_tourbox_orbit_probe_result(
    mode,
    wheel_label,
    start_angle,
    target_angle,
    raw_handle,
    after_handle,
    report_path,
):
    if after_handle:
        print(
            "tourbox orbit probe "
            f"{mode} {wheel_label} "
            f"angle={math.degrees(start_angle):.1f}->{math.degrees(target_angle):.1f} "
            f"handle=({raw_handle['x']:.1f},{raw_handle['y']:.1f})->"
            f"({after_handle['x']:.1f},{after_handle['y']:.1f}) "
            f"report={report_path}"
        )
    else:
        print(f"tourbox orbit probe {mode} finished without after-handle report={report_path}")


__all__ = [
    'print_tourbox_offscreen_probe_result',
    'print_tourbox_orbit_probe_result',
    'tourbox_area_snapshot',
    'tourbox_offscreen_probe_report',
    'tourbox_orbit_probe_report',
    'tourbox_point_list',
    'tourbox_radius_target_report',
    'write_tourbox_probe_report',
]
