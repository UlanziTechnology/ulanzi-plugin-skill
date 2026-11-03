"""TourBox probe config and diagnostic report helpers."""

import math
import time

from ..wheel_diameter_geometry import wheel_diameter_max_radius
from .tourbox_probe_runtime import (
    DIAGNOSTICS_DIR,
    TOURBOX_PROBE_CONFIG_PATH,
    TourBoxMouseInput,
    TourBoxProbeConfigAccessor,
    TourBoxProbeEventRecorder,
    create_tourbox_probe_run_dir,
    load_tourbox_probe_config,
    tourbox_probe_config_getter,
    tourbox_probe_run_context,
)
from .tourbox_probe_reports import (
    print_tourbox_offscreen_probe_result,
    print_tourbox_orbit_probe_result,
    tourbox_area_snapshot,
    tourbox_offscreen_probe_report,
    tourbox_orbit_probe_report,
    tourbox_point_list,
    tourbox_radius_target_report,
    write_tourbox_probe_report,
)


def find_tourbox_probe_area(areas, current_hover_area, recent_wheel_area_fn, wheel_name):
    area = next(
        (
            item for item in areas
            if item.get('type') == 'wheel'
            and item.get('name', '').lower() == str(wheel_name).lower()
        ),
        None,
    )
    if area is None:
        area = (
            current_hover_area
            if current_hover_area and current_hover_area.get('type') == 'wheel'
            else None
        )
    if area is None and recent_wheel_area_fn:
        area = recent_wheel_area_fn()
    return area


def tourbox_probe_prepare_area(
    areas,
    current_hover_area,
    recent_wheel_area_fn,
    wheel_name,
    *,
    release_param_drag_fn,
    release_wheel_drag_fn,
    release_wheel_orbit_drag_fn,
):
    release_param_drag_fn()
    release_wheel_drag_fn()
    release_wheel_orbit_drag_fn()
    return find_tourbox_probe_area(
        areas,
        current_hover_area,
        recent_wheel_area_fn,
        wheel_name,
    )


def tourbox_orbit_execute_split_plan(split_plan, run_probe_fn, *, mode, wheel_name):
    if not split_plan['should_split']:
        return None

    split_count = split_plan['split_count']
    split_tick = split_plan['split_tick']
    split_delay = split_plan['split_delay']
    ok_all = True
    for split_index in range(split_count):
        if split_index > 0 and split_delay > 0.0:
            time.sleep(split_delay)
        ok_all = run_probe_fn(
            ticks=split_tick,
            mode=mode,
            wheel_name=wheel_name,
        ) and ok_all
        if not ok_all:
            break
    return ok_all


def tourbox_offscreen_state_context(probe_state, target_key, *, config_get, now=None):
    probe_state = probe_state if isinstance(probe_state, dict) else None
    axis_lock_seconds = max(0.0, float(config_get('axis_lock_seconds', 6.0)))
    center_bridge_seconds = max(0.0, float(config_get('center_bridge_seconds', 1.5)))
    state_timeout_seconds = (
        center_bridge_seconds
        if probe_state and probe_state.get('source') == 'center_bridge'
        else axis_lock_seconds
    )
    now = time.time() if now is None else now
    state_is_current = (
        probe_state
        and probe_state.get('target_key') == target_key
        and now - probe_state.get('updated_at', 0.0) <= state_timeout_seconds
    )
    return {
        'probe_state': probe_state,
        'axis_lock_seconds': axis_lock_seconds,
        'center_bridge_seconds': center_bridge_seconds,
        'state_timeout_seconds': state_timeout_seconds,
        'state_is_current': state_is_current,
    }


def tourbox_offscreen_start_plan(
    area,
    target_key,
    probe_state_before,
    ticks,
    *,
    detect_wheel_circle_fn,
    detect_raw_handle_fn,
    config_get,
):
    wheel_geometry = detect_wheel_circle_fn(area)
    state_context = tourbox_offscreen_state_context(
        probe_state_before,
        target_key,
        config_get=config_get,
    )
    probe_state = state_context['probe_state']
    state_is_current = state_context['state_is_current']
    raw_handle = detect_raw_handle_fn(area)
    if raw_handle and wheel_geometry:
        raw_handle.update(wheel_geometry)

    geometry_context = tourbox_probe_wheel_geometry_context(raw_handle, wheel_geometry, area)
    center_x = geometry_context['center_x']
    center_y = geometry_context['center_y']
    wheel_radius = geometry_context['wheel_radius']
    max_handle_radius = wheel_diameter_max_radius(area, center_x, center_y, wheel_radius)
    axis_mode = str(config_get('axis_mode', 'fixed_axis')).lower()
    prediction_enabled = bool(config_get('prediction_enabled', False))
    center_bridge_enabled = bool(config_get('center_bridge_enabled', True))
    center_bridge_radius_px = max(0.0, float(config_get('center_bridge_radius_px', 18.0)))

    start_selection = tourbox_offscreen_select_start_handle(
        raw_handle,
        probe_state,
        state_is_current=bool(state_is_current),
        prediction_enabled=prediction_enabled,
        axis_mode=axis_mode,
        center_bridge_enabled=center_bridge_enabled,
        center_fallback_when_missing=bool(config_get('center_fallback_when_handle_missing', True)),
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
        config_get=config_get,
    )
    raw_handle = start_selection['raw_handle']
    handle = start_selection['handle']
    if not handle:
        return {
            'ok': False,
            'reason': 'handle_not_found',
        }

    start_x = float(handle['x'])
    start_y = float(handle['y'])
    direction_multiplier = -1 if bool(config_get('invert_tick_direction', False)) else 1
    direction = (1 if ticks >= 0 else -1) * direction_multiplier

    handle_dx = start_x - center_x
    handle_dy = start_y - center_y
    handle_radius = math.hypot(handle_dx, handle_dy)
    axis_angle, axis_source = tourbox_offscreen_axis_selection(
        axis_mode=axis_mode,
        probe_state=probe_state,
        state_is_current=bool(state_is_current),
        handle_radius=handle_radius,
        handle_dx=handle_dx,
        handle_dy=handle_dy,
        center_bridge_radius_px=center_bridge_radius_px,
        config_get=config_get,
    )
    start_x, start_y, bridge_info = tourbox_offscreen_center_bridge_projection(
        center_bridge_enabled=center_bridge_enabled,
        handle_radius=handle_radius,
        center_bridge_radius_px=center_bridge_radius_px,
        handle_source=start_selection['handle_source'],
        start_x=start_x,
        start_y=start_y,
        center_x=center_x,
        center_y=center_y,
        axis_angle=axis_angle,
    )
    line_plan = tourbox_offscreen_line_plan(
        start_x=start_x,
        start_y=start_y,
        center_x=center_x,
        center_y=center_y,
        axis_angle=axis_angle,
        direction=direction,
        wheel_radius=wheel_radius,
        max_handle_radius=max_handle_radius,
        config_get=config_get,
    )

    return {
        'ok': True,
        'wheel_geometry': wheel_geometry,
        'state_context': state_context,
        'probe_state': probe_state,
        'axis_lock_seconds': state_context['axis_lock_seconds'],
        'center_bridge_seconds': state_context['center_bridge_seconds'],
        'state_is_current': state_is_current,
        'raw_handle': raw_handle,
        'geometry_context': geometry_context,
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
        'max_handle_radius': max_handle_radius,
        'axis_mode': axis_mode,
        'prediction_enabled': prediction_enabled,
        'center_bridge_enabled': center_bridge_enabled,
        'center_bridge_radius_px': center_bridge_radius_px,
        'start_selection': start_selection,
        'predicted_start_handle': start_selection['predicted_start_handle'],
        'bridge_start_handle': start_selection['bridge_start_handle'],
        'before_suspicion_reason': start_selection['before_suspicion_reason'],
        'handle': handle,
        'handle_source': start_selection['handle_source'],
        'start_x': start_x,
        'start_y': start_y,
        'direction_multiplier': direction_multiplier,
        'direction': direction,
        'handle_dx': handle_dx,
        'handle_dy': handle_dy,
        'handle_radius': handle_radius,
        'axis_angle': axis_angle,
        'axis_source': axis_source,
        'bridge_info': bridge_info,
        'line_plan': line_plan,
        'start_signed_axis': line_plan['start_signed_axis'],
        'start_perpendicular_axis': line_plan['start_perpendicular_axis'],
        'line_distance_requested_px': line_plan['line_distance_requested_px'],
        'line_distance_px': line_plan['line_distance_px'],
        'guard_info': line_plan['guard_info'],
        'line_steps': line_plan['line_steps'],
        'line_points': line_plan['line_points'],
        'predicted_after': line_plan['predicted_after'],
    }


def tourbox_probe_wheel_geometry_context(raw_handle, wheel_geometry, area):
    center_x = (
        raw_handle.get('wheel_center_x')
        if raw_handle
        else (
            wheel_geometry['wheel_center_x']
            if wheel_geometry
            else area.get('center_x', area['x'] + area['w'] / 2)
        )
    )
    center_y = (
        raw_handle.get('wheel_center_y')
        if raw_handle
        else (
            wheel_geometry['wheel_center_y']
            if wheel_geometry
            else area.get('center_y', area['y'] + area['h'] / 2)
        )
    )
    wheel_radius = (
        raw_handle.get('wheel_radius')
        if raw_handle and raw_handle.get('wheel_radius')
        else (
            wheel_geometry['wheel_radius']
            if wheel_geometry and wheel_geometry.get('wheel_radius')
            else min(area['w'], area['h']) / 2
        )
    )
    return {
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
    }


def tourbox_center_handle(center_x, center_y, wheel_radius, source, *, updated_at=None):
    return {
        'x': float(center_x),
        'y': float(center_y),
        'count': 0,
        'score': None,
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'wheel_radius': wheel_radius,
        'source': source,
        'updated_at': time.time() if updated_at is None else updated_at,
    }


def tourbox_predicted_handle(probe_state, center_x, center_y, wheel_radius, source, *, updated_at=None):
    if not isinstance(probe_state, dict):
        return None
    predicted_x = probe_state.get('predicted_handle_x')
    predicted_y = probe_state.get('predicted_handle_y')
    if predicted_x is None or predicted_y is None:
        return None
    return {
        'x': float(predicted_x),
        'y': float(predicted_y),
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'wheel_radius': wheel_radius,
        'score': None,
        'count': None,
        'source': source,
        'updated_at': time.time() if updated_at is None else updated_at,
    }


def tourbox_state_prediction_handle(
    probe_state,
    *,
    state_is_current,
    prediction_enabled,
    axis_mode,
    center_x,
    center_y,
    wheel_radius,
):
    if not prediction_enabled or axis_mode not in {'locked_axis', 'session_axis'}:
        return None
    if not state_is_current:
        return None
    return tourbox_predicted_handle(
        probe_state,
        center_x,
        center_y,
        wheel_radius,
        'prediction',
    )


def tourbox_center_bridge_handle(
    probe_state,
    *,
    state_is_current,
    center_bridge_enabled,
    center_x,
    center_y,
    wheel_radius,
):
    if not center_bridge_enabled:
        return None
    if not state_is_current or probe_state.get('source') != 'center_bridge':
        return None
    return tourbox_predicted_handle(
        probe_state,
        center_x,
        center_y,
        wheel_radius,
        'center_bridge',
    )


def tourbox_detection_suspicion_reason(
    candidate,
    predicted=None,
    *,
    center_x,
    center_y,
    prediction_enabled,
    config_get,
):
    if not candidate:
        return 'missing'
    if candidate.get('source') == 'center_fallback':
        return None
    score = candidate.get('score')
    bad_score_below = float(config_get('bad_detection_score_below', 0.0))
    if score is not None and float(score) < bad_score_below:
        return 'bad_score'
    if predicted and prediction_enabled:
        raw_radius = math.hypot(candidate['x'] - center_x, candidate['y'] - center_y)
        center_prediction_radius_px = max(
            0.0,
            float(config_get('center_prediction_radius_px', 14.0)),
        )
        center_prediction_score_below = float(
            config_get('center_prediction_score_below', 3.0)
        )
        center_prediction_count_below = int(
            config_get('center_prediction_count_below', 4)
        )
        count = candidate.get('count')
        ambiguous_near_center = (
            raw_radius <= center_prediction_radius_px
            and (
                score is None
                or float(score) < center_prediction_score_below
                or (count is not None and int(count) < center_prediction_count_below)
            )
        )
        max_jump = float(config_get('prediction_max_detect_jump_px', 36.0))
        jump = math.hypot(candidate['x'] - predicted['x'], candidate['y'] - predicted['y'])
        if ambiguous_near_center and jump > max_jump:
            return 'ambiguous_center_jump'
    return None


def tourbox_offscreen_select_start_handle(
    raw_handle,
    probe_state,
    *,
    state_is_current,
    prediction_enabled,
    axis_mode,
    center_bridge_enabled,
    center_fallback_when_missing,
    center_x,
    center_y,
    wheel_radius,
    config_get,
):
    if raw_handle is None and center_fallback_when_missing:
        raw_handle = tourbox_center_handle(
            center_x,
            center_y,
            wheel_radius,
            'center_fallback',
        )

    predicted_start_handle = tourbox_state_prediction_handle(
        probe_state,
        state_is_current=bool(state_is_current),
        prediction_enabled=prediction_enabled,
        axis_mode=axis_mode,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
    )
    bridge_start_handle = tourbox_center_bridge_handle(
        probe_state,
        state_is_current=bool(state_is_current),
        center_bridge_enabled=center_bridge_enabled,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
    )
    before_suspicion_reason = tourbox_detection_suspicion_reason(
        raw_handle,
        predicted_start_handle,
        center_x=center_x,
        center_y=center_y,
        prediction_enabled=prediction_enabled,
        config_get=config_get,
    )
    if before_suspicion_reason:
        if bridge_start_handle:
            handle = bridge_start_handle
            handle_source = 'center_bridge'
        elif center_bridge_enabled and before_suspicion_reason in {'missing', 'bad_score'}:
            handle = tourbox_center_handle(
                center_x,
                center_y,
                wheel_radius,
                'center_bad_detection_fallback',
            )
            handle_source = 'center_bad_detection_fallback'
        else:
            handle = predicted_start_handle
            handle_source = 'prediction'
    else:
        handle = raw_handle
        handle_source = raw_handle.get('source') or 'detected'

    return {
        'raw_handle': raw_handle,
        'predicted_start_handle': predicted_start_handle,
        'bridge_start_handle': bridge_start_handle,
        'before_suspicion_reason': before_suspicion_reason,
        'handle': handle,
        'handle_source': handle_source,
    }


def tourbox_canonical_diameter_axis(angle, cardinal_threshold_deg):
    unit_x = math.cos(angle)
    unit_y = math.sin(angle)
    cardinal_threshold = math.tan(math.radians(float(cardinal_threshold_deg)))
    if abs(unit_y) <= abs(unit_x) * cardinal_threshold:
        if unit_x > 0:
            angle += math.pi
    elif abs(unit_x) <= abs(unit_y) * cardinal_threshold:
        if unit_y > 0:
            angle += math.pi
    elif unit_y < 0:
        angle += math.pi
    return math.atan2(math.sin(angle), math.cos(angle))


def tourbox_offscreen_axis_selection(
    *,
    axis_mode,
    probe_state,
    state_is_current,
    handle_radius,
    handle_dx,
    handle_dy,
    center_bridge_radius_px,
    config_get,
):
    state = probe_state if isinstance(probe_state, dict) else {}
    config_axis = math.radians(float(config_get('axis_angle_deg', -49.5)))
    if axis_mode in {'fixed_axis', 'config_axis', 'configured_axis'}:
        return config_axis, 'config'
    if axis_mode in {'diameter_axis', 'current_diameter', 'handle_diameter'}:
        if (
            state_is_current
            and state.get('source') == 'center_bridge'
            and handle_radius <= center_bridge_radius_px
        ):
            return float(state['axis_angle']), 'center_bridge_axis'
        if handle_radius >= 3.0:
            return (
                tourbox_canonical_diameter_axis(
                    math.atan2(handle_dy, handle_dx),
                    config_get('diameter_axis_cardinal_threshold_deg', 22.5),
                ),
                'diameter_handle',
            )
        if state_is_current and state.get('source') == 'center_bridge':
            return float(state['axis_angle']), 'center_bridge_axis'
        return config_axis, 'config'
    if axis_mode in {'locked_axis', 'session_axis'} and state_is_current:
        return float(state['axis_angle']), 'locked'
    if axis_mode in {'locked_axis', 'session_axis', 'handle_axis', 'radial', 'current'} and handle_radius >= 3.0:
        return math.atan2(handle_dy, handle_dx), 'handle'
    return config_axis, 'fallback'


def tourbox_offscreen_center_bridge_projection(
    *,
    center_bridge_enabled,
    handle_radius,
    center_bridge_radius_px,
    handle_source,
    start_x,
    start_y,
    center_x,
    center_y,
    axis_angle,
):
    if not (
        center_bridge_enabled
        and handle_radius <= center_bridge_radius_px
        and handle_source in {'detected', 'center_fallback', 'center_bad_detection_fallback'}
    ):
        return start_x, start_y, None

    original_start_x = start_x
    original_start_y = start_y
    signed_near_center = (
        (start_x - center_x) * math.cos(axis_angle)
        + (start_y - center_y) * math.sin(axis_angle)
    )
    projected_x = center_x + math.cos(axis_angle) * signed_near_center
    projected_y = center_y + math.sin(axis_angle) * signed_near_center
    return projected_x, projected_y, {
        'type': 'project_near_center_to_axis',
        'radius_px': round(handle_radius, 3),
        'threshold_px': round(center_bridge_radius_px, 3),
        'original_start': [round(original_start_x, 3), round(original_start_y, 3)],
        'projected_start': [round(projected_x, 3), round(projected_y, 3)],
        'signed_start': round(signed_near_center, 3),
    }


def tourbox_offscreen_select_after_handle(
    after_raw_handle,
    predicted_after,
    *,
    wheel_geometry,
    center_x,
    center_y,
    prediction_enabled,
    center_bridge_enabled,
    config_get,
):
    if after_raw_handle and wheel_geometry:
        after_raw_handle.update(wheel_geometry)
    after_suspicion_reason = tourbox_detection_suspicion_reason(
        after_raw_handle,
        predicted_after,
        center_x=center_x,
        center_y=center_y,
        prediction_enabled=prediction_enabled,
        config_get=config_get,
    )
    if prediction_enabled and after_suspicion_reason:
        after_handle = predicted_after
        after_source = 'prediction'
    elif center_bridge_enabled and after_suspicion_reason in {'missing', 'bad_score'}:
        after_handle = predicted_after
        after_source = 'center_bridge'
    else:
        after_handle = after_raw_handle
        after_source = 'detected'
    return {
        'after_raw_handle': after_raw_handle,
        'after_suspicion_reason': after_suspicion_reason,
        'after_handle': after_handle,
        'after_source': after_source,
    }


def tourbox_exception_after_handle_context(
    after_raw_handle,
    *,
    after_source='detected',
    after_suspicion_reason=None,
):
    return {
        'after_raw_handle': after_raw_handle,
        'after_handle': after_raw_handle,
        'after_source': after_source,
        'after_suspicion_reason': after_suspicion_reason,
    }


def tourbox_probe_exception_context(
    *,
    area,
    send_left_up_fn,
    detect_raw_handle_fn,
    record_fn,
):
    send_left_up_fn()
    exception_context = tourbox_exception_after_handle_context(
        detect_raw_handle_fn(area),
    )
    record_fn('exception', ok=False)
    return exception_context


def tourbox_offscreen_after_drag_context(
    *,
    area,
    predicted_after,
    wheel_geometry,
    center_x,
    center_y,
    prediction_enabled,
    center_bridge_enabled,
    config_get,
    detect_raw_handle_fn,
    final_cursor_policy,
    original_cursor,
    line_points,
):
    time.sleep(0.12)
    after_raw_handle = detect_raw_handle_fn(area)
    after_selection = tourbox_offscreen_select_after_handle(
        after_raw_handle,
        predicted_after,
        wheel_geometry=wheel_geometry,
        center_x=center_x,
        center_y=center_y,
        prediction_enabled=prediction_enabled,
        center_bridge_enabled=center_bridge_enabled,
        config_get=config_get,
    )
    final_cursor_target = tourbox_final_cursor_target(
        final_cursor_policy,
        after_selection['after_handle'],
        original_cursor,
        line_points,
        end_source='line_end',
        missing_handle_source='original_fallback',
    )
    after_selection['final_cursor_target'] = final_cursor_target
    return after_selection


def tourbox_offscreen_line_plan(
    *,
    start_x,
    start_y,
    center_x,
    center_y,
    axis_angle,
    direction,
    wheel_radius,
    max_handle_radius,
    config_get,
    updated_at=None,
):
    start_signed_axis = (
        (start_x - center_x) * math.cos(axis_angle)
        + (start_y - center_y) * math.sin(axis_angle)
    )
    start_perpendicular_axis = abs(
        (start_x - center_x) * math.sin(axis_angle)
        - (start_y - center_y) * math.cos(axis_angle)
    )
    line_distance_requested_px = float(config_get('line_distance_px', max(560.0, wheel_radius * 9.0)))
    line_distance_px = line_distance_requested_px
    center_deadzone_px = max(0.0, float(config_get('center_deadzone_px', 18.0)))
    center_policy = str(config_get('center_policy', 'stop_before')).lower()
    guard_info = None
    if center_policy in {'stop_before', 'clamp', 'no_cross'} and center_deadzone_px > 0:
        unit_x = math.cos(axis_angle) * direction
        unit_y = math.sin(axis_angle) * direction
        rel_x = start_x - center_x
        rel_y = start_y - center_y
        distance_to_center_along_ray = -(rel_x * unit_x + rel_y * unit_y)
        perpendicular_distance = abs(rel_x * unit_y - rel_y * unit_x)
        if (
            0 < distance_to_center_along_ray < line_distance_requested_px
            and perpendicular_distance <= center_deadzone_px
        ):
            line_distance_px = max(0.0, distance_to_center_along_ray - center_deadzone_px)
            guard_info = {
                'policy': center_policy,
                'deadzone_px': center_deadzone_px,
                'requested_distance_px': round(line_distance_requested_px, 3),
                'adjusted_distance_px': round(line_distance_px, 3),
                'distance_to_center_along_ray': round(distance_to_center_along_ray, 3),
                'perpendicular_distance': round(perpendicular_distance, 3),
            }

    line_steps = max(2, int(config_get('line_steps', 36)))
    if line_distance_px < 1.0:
        line_steps = 1
    line_step = line_distance_px / line_steps * direction
    line_points = []
    for index in range(1, line_steps + 1):
        distance = line_step * index
        line_points.append((
            start_x + math.cos(axis_angle) * distance,
            start_y + math.sin(axis_angle) * distance,
        ))

    signed_target = max(
        -max_handle_radius,
        min(max_handle_radius, start_signed_axis + direction * line_distance_px),
    )
    predicted_after = {
        'x': center_x + math.cos(axis_angle) * signed_target,
        'y': center_y + math.sin(axis_angle) * signed_target,
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'wheel_radius': wheel_radius,
        'score': None,
        'count': None,
        'source': 'prediction',
        'signed_radius': signed_target,
        'updated_at': time.time() if updated_at is None else updated_at,
    }
    return {
        'start_signed_axis': start_signed_axis,
        'start_perpendicular_axis': start_perpendicular_axis,
        'line_distance_requested_px': line_distance_requested_px,
        'line_distance_px': line_distance_px,
        'center_deadzone_px': center_deadzone_px,
        'center_policy': center_policy,
        'guard_info': guard_info,
        'line_steps': line_steps,
        'line_points': line_points,
        'signed_target': signed_target,
        'predicted_after': predicted_after,
    }


def tourbox_offscreen_probe_state_payload(
    *,
    center_bridge_enabled,
    result_error,
    bridge_info,
    before_suspicion_reason,
    after_suspicion_reason,
    axis_mode,
    target_key,
    axis_angle,
    after_handle,
    predicted_after,
    axis_source,
    updated_at=None,
):
    if result_error is not None:
        return None

    state_source = None
    if (
        center_bridge_enabled
        and (
            bridge_info
            or before_suspicion_reason in {'missing', 'bad_score'}
            or after_suspicion_reason in {'missing', 'bad_score'}
        )
    ):
        state_source = 'center_bridge'
    elif axis_mode in {'locked_axis', 'session_axis'}:
        state_source = axis_source

    if state_source is None:
        return None

    return {
        'target_key': target_key,
        'axis_angle': axis_angle,
        'axis_angle_deg': round(math.degrees(axis_angle), 3),
        'predicted_handle_x': after_handle.get('x') if after_handle else predicted_after['x'],
        'predicted_handle_y': after_handle.get('y') if after_handle else predicted_after['y'],
        'updated_at': time.time() if updated_at is None else updated_at,
        'source': state_source,
    }


def tourbox_arc_points(center_x, center_y, start_angle, delta_angle, radius, end_radius, steps):
    if end_radius is None:
        end_radius = radius
    return [
        (
            center_x + math.cos(start_angle + delta_angle * index / steps)
            * (radius + (end_radius - radius) * index / steps),
            center_y + math.sin(start_angle + delta_angle * index / steps)
            * (radius + (end_radius - radius) * index / steps),
        )
        for index in range(0, steps + 1)
    ]


def tourbox_handle_polar(handle, center_x, center_y):
    dx = float(handle['x']) - center_x
    dy = float(handle['y']) - center_y
    return math.hypot(dx, dy), math.atan2(dy, dx)


def tourbox_orbit_predictive_start_handle(
    predictive_cache_before,
    *,
    predictive_enabled,
    predictive_key,
    predictive_now,
    predictive_cache_seconds,
    predictive_center_tolerance,
    area,
):
    result = {
        'wheel_geometry': None,
        'raw_handle': None,
        'predictive_start_source': 'detected',
    }
    if not predictive_enabled or not isinstance(predictive_cache_before, dict):
        return result

    try:
        same_wheel = predictive_cache_before.get('key') == predictive_key
        fresh = (
            predictive_now - float(predictive_cache_before.get('updated_at', 0.0))
            <= predictive_cache_seconds
        )
        cached_center_x = float(predictive_cache_before.get('wheel_center_x'))
        cached_center_y = float(predictive_cache_before.get('wheel_center_y'))
        area_center_x = area.get('center_x', area['x'] + area['w'] / 2)
        area_center_y = area.get('center_y', area['y'] + area['h'] / 2)
        same_center = (
            abs(cached_center_x - float(area_center_x)) <= predictive_center_tolerance
            and abs(cached_center_y - float(area_center_y)) <= predictive_center_tolerance
        )
        if same_wheel and fresh and same_center:
            wheel_geometry = {
                'wheel_center_x': cached_center_x,
                'wheel_center_y': cached_center_y,
                'wheel_radius': float(predictive_cache_before.get('wheel_radius')),
            }
            result.update({
                'wheel_geometry': wheel_geometry,
                'raw_handle': {
                    'x': float(predictive_cache_before.get('x')),
                    'y': float(predictive_cache_before.get('y')),
                    'count': None,
                    'score': None,
                    'wheel_center_x': wheel_geometry['wheel_center_x'],
                    'wheel_center_y': wheel_geometry['wheel_center_y'],
                    'wheel_radius': wheel_geometry['wheel_radius'],
                    'updated_at': time.time(),
                    'source': 'orbit_predictive_cache',
                },
                'predictive_start_source': 'predictive_cache',
            })
    except Exception:
        result['wheel_geometry'] = None
        result['raw_handle'] = None
        result['predictive_start_source'] = 'detected'
    return result


def tourbox_orbit_start_detection_context(
    predictive_cache_before,
    *,
    predictive_enabled,
    predictive_key,
    predictive_now,
    predictive_cache_seconds,
    predictive_center_tolerance,
    area,
    detect_wheel_circle_fn,
    detect_raw_handle_fn,
):
    predictive_start = tourbox_orbit_predictive_start_handle(
        predictive_cache_before,
        predictive_enabled=predictive_enabled,
        predictive_key=predictive_key,
        predictive_now=predictive_now,
        predictive_cache_seconds=predictive_cache_seconds,
        predictive_center_tolerance=predictive_center_tolerance,
        area=area,
    )
    predictive_start_source = predictive_start['predictive_start_source']
    wheel_geometry = predictive_start['wheel_geometry']
    raw_handle = predictive_start['raw_handle']

    if raw_handle is None:
        wheel_geometry = detect_wheel_circle_fn(area)
        raw_handle = detect_raw_handle_fn(area)
        if raw_handle and wheel_geometry:
            raw_handle.update(wheel_geometry)

    return {
        'predictive_start_source': predictive_start_source,
        'wheel_geometry': wheel_geometry,
        'raw_handle': raw_handle,
    }


def tourbox_orbit_split_tick_plan(ticks, *, config_get):
    try:
        ticks_int = int(ticks)
    except Exception:
        ticks_int = 1
    enabled = bool(config_get('orbit_split_ticks_enabled', False))
    if not enabled or abs(ticks_int) <= 1:
        return {
            'should_split': False,
            'ticks_int': ticks_int,
            'split_count': 0,
            'split_tick': ticks_int,
            'split_delay': 0.0,
        }
    return {
        'should_split': True,
        'ticks_int': ticks_int,
        'split_count': min(
            abs(ticks_int),
            max(1, int(config_get('orbit_max_ticks_per_event', 3))),
        ),
        'split_tick': 1 if ticks_int > 0 else -1,
        'split_delay': max(0.0, float(config_get('orbit_split_tick_delay_seconds', 0.01))),
    }


def tourbox_orbit_radius_target_context(
    radius_target_before,
    *,
    radius_target_enabled,
    wheel_key,
    target_now,
    predictive_start_source,
    handle_radius,
    min_handle_radius,
    center_x,
    center_y,
    config_get,
):
    radius_target_source = 'current'
    radius_target = handle_radius
    target_seconds = 0.0
    target_reset_px = 0.0
    target_center_tolerance = 0.0

    if radius_target_enabled:
        target_seconds = max(0.0, float(config_get('orbit_radius_target_seconds', 12.0)))
        target_reset_px = max(0.0, float(config_get('orbit_radius_target_manual_reset_px', 8.0)))
        target_center_tolerance = max(
            0.0,
            float(config_get('orbit_radius_target_center_tolerance_px', 6.0)),
        )
        if isinstance(radius_target_before, dict):
            try:
                same_wheel = radius_target_before.get('key') == wheel_key
                same_center = (
                    abs(float(radius_target_before.get('center_x', center_x)) - center_x)
                    <= target_center_tolerance
                    and abs(float(radius_target_before.get('center_y', center_y)) - center_y)
                    <= target_center_tolerance
                )
                fresh = (
                    target_now - float(radius_target_before.get('updated_at', 0.0))
                    <= target_seconds
                )
                last_observed_radius = float(
                    radius_target_before.get('last_observed_radius', handle_radius)
                )
                manual_reset = (
                    predictive_start_source == 'detected'
                    and target_reset_px > 0.0
                    and abs(handle_radius - last_observed_radius) > target_reset_px
                )
                if same_wheel and same_center and fresh and not manual_reset:
                    radius_target = float(radius_target_before.get('target_radius', handle_radius))
                    radius_target_source = 'target_state'
            except Exception:
                radius_target_before = None
        radius_target = max(min_handle_radius, radius_target)

    return {
        'enabled': radius_target_enabled,
        'source': radius_target_source,
        'before': radius_target_before,
        'target_radius': radius_target,
        'target_seconds': target_seconds,
        'target_reset_px': target_reset_px,
        'target_center_tolerance': target_center_tolerance,
    }


def tourbox_orbit_tick_context(
    *,
    ticks,
    start_angle,
    desired_radius,
    min_handle_radius,
    config_get,
):
    tick_direction = 1 if ticks >= 0 else -1
    if bool(config_get('orbit_invert_tick_direction', False)):
        tick_direction *= -1
    degrees_per_tick = float(config_get('orbit_degrees_per_tick', 16.0))
    max_degrees = abs(float(config_get('orbit_max_degrees_per_event', 54.0)))
    max_ticks = max(1, int(config_get('orbit_max_ticks_per_event', 3)))
    tick_magnitude = max(1, min(abs(int(ticks)), max_ticks))
    delta_degrees = tick_direction * min(max_degrees, degrees_per_tick * tick_magnitude)
    delta_angle = math.radians(delta_degrees)
    mouse_angle_gain = float(config_get('orbit_mouse_angle_gain', 1.0))
    mouse_delta_angle = delta_angle * mouse_angle_gain
    target_angle = start_angle + delta_angle
    handle_angle_response_gain = float(config_get('orbit_handle_angle_response_gain', 0.10))
    handle_radius_response_per_tick = float(config_get('orbit_handle_radius_response_per_tick_px', 0.0))
    predicted_handle_angle = start_angle + delta_angle * handle_angle_response_gain
    predicted_handle_radius = max(
        min_handle_radius,
        desired_radius + handle_radius_response_per_tick * tick_magnitude,
    )
    return {
        'tick_direction': tick_direction,
        'degrees_per_tick': degrees_per_tick,
        'max_degrees': max_degrees,
        'max_ticks': max_ticks,
        'tick_magnitude': tick_magnitude,
        'delta_degrees': delta_degrees,
        'delta_angle': delta_angle,
        'mouse_angle_gain': mouse_angle_gain,
        'mouse_delta_angle': mouse_delta_angle,
        'target_angle': target_angle,
        'handle_angle_response_gain': handle_angle_response_gain,
        'handle_radius_response_per_tick': handle_radius_response_per_tick,
        'predicted_handle_angle': predicted_handle_angle,
        'predicted_handle_radius': predicted_handle_radius,
    }


def tourbox_orbit_arc_motion_plan(
    *,
    mode,
    start_x,
    start_y,
    center_x,
    center_y,
    start_angle,
    handle_radius,
    desired_radius,
    wheel_radius,
    min_handle_radius,
    radius_target_enabled,
    radius_target,
    mouse_delta_angle,
    config_get,
):
    mode = str(mode or 'local_arc').lower()
    if mode not in {'local_arc', 'manual_arc'}:
        mode = 'local_arc'

    local_radius_bias = 0.0
    local_radius_bias_from_radius = 0.0
    local_radius_bias_from_error = 0.0
    arc_source = 'local'
    arc_radius = max(desired_radius, float(config_get('orbit_local_radius_min_px', 18.0)))
    max_radius_bias = max(0.0, float(config_get('orbit_local_radius_bias_max_px', 4.0)))
    press_x = start_x
    press_y = start_y
    press_radius = handle_radius
    press_source = 'handle_center'

    if radius_target_enabled and bool(config_get('orbit_radius_target_bias_enabled', True)):
        pivot_radius = float(config_get('orbit_radius_target_bias_pivot_radius_px', 26.0))
        pivot_bias = float(config_get('orbit_radius_target_bias_pivot_px', 2.4))
        radius_gain = float(config_get('orbit_radius_target_bias_radius_gain', 0.12))
        error_gain = float(config_get('orbit_radius_target_bias_error_gain', 0.18))
        min_radius_bias = max(0.0, float(config_get('orbit_radius_target_bias_min_px', 0.0)))
        local_radius_bias_from_radius = (radius_target - pivot_radius) * radius_gain
        local_radius_bias_from_error = (radius_target - handle_radius) * error_gain
        local_radius_bias = max(
            min_radius_bias,
            min(
                max_radius_bias,
                pivot_bias + local_radius_bias_from_radius + local_radius_bias_from_error,
            ),
        )

    arc_end_radius = arc_radius + local_radius_bias
    outer_edge_clamp_report = None
    if bool(config_get('orbit_outer_edge_clamp_enabled', True)) and wheel_radius > 0:
        outer_edge_trigger = max(0.0, float(config_get('orbit_outer_edge_trigger_px', 3.0)))
        outer_edge_inset = max(0.0, float(config_get('orbit_outer_edge_inset_px', 1.5)))
        outer_edge_triggered = handle_radius >= wheel_radius - outer_edge_trigger
        if outer_edge_triggered:
            max_drag_radius = max(min_handle_radius, wheel_radius - outer_edge_inset)
            unclamped_arc_radius = arc_radius
            unclamped_arc_end_radius = arc_end_radius
            arc_radius = min(arc_radius, max_drag_radius)
            arc_end_radius = min(arc_end_radius, max_drag_radius)
            press_inset = max(outer_edge_inset, float(config_get('orbit_outer_edge_press_inset_px', 4.5)))
            press_radius = min(handle_radius, max(min_handle_radius, wheel_radius - press_inset))
            press_x = center_x + math.cos(start_angle) * press_radius
            press_y = center_y + math.sin(start_angle) * press_radius
            press_source = 'outer_edge_inset'
            outer_edge_clamp_report = {
                'enabled': True,
                'triggered': True,
                'trigger_px': round(outer_edge_trigger, 3),
                'inset_px': round(outer_edge_inset, 3),
                'press_inset_px': round(press_inset, 3),
                'max_drag_radius_px': round(max_drag_radius, 3),
                'press_radius_px': round(press_radius, 3),
                'arc_radius_before_px': round(unclamped_arc_radius, 3),
                'arc_end_radius_before_px': round(unclamped_arc_end_radius, 3),
                'applied': arc_radius != unclamped_arc_radius or arc_end_radius != unclamped_arc_end_radius,
            }

    arc_step_degrees = max(1.0, float(config_get('orbit_arc_step_degrees', 5.0)))
    arc_max_steps = max(3, int(config_get('orbit_arc_max_steps', 18)))
    arc_steps = min(
        arc_max_steps,
        max(4, int(math.ceil(abs(math.degrees(mouse_delta_angle)) / arc_step_degrees))),
    )
    arc_points = tourbox_arc_points(
        center_x,
        center_y,
        start_angle,
        mouse_delta_angle,
        arc_radius,
        arc_end_radius,
        arc_steps,
    )

    return {
        'mode': mode,
        'arc_source': arc_source,
        'arc_radius': arc_radius,
        'arc_end_radius': arc_end_radius,
        'arc_steps': arc_steps,
        'arc_points': arc_points,
        'local_radius_bias': local_radius_bias,
        'local_radius_bias_from_radius': local_radius_bias_from_radius,
        'local_radius_bias_from_error': local_radius_bias_from_error,
        'outer_edge_clamp_report': outer_edge_clamp_report,
        'press_x': press_x,
        'press_y': press_y,
        'press_radius': press_radius,
        'press_source': press_source,
    }


def tourbox_orbit_predicted_after_handle(
    *,
    center_x,
    center_y,
    wheel_radius,
    predicted_handle_angle,
    predicted_handle_radius,
    target_angle,
    handle_angle_response_gain,
    updated_at=None,
):
    return {
        'x': center_x + math.cos(predicted_handle_angle) * predicted_handle_radius,
        'y': center_y + math.sin(predicted_handle_angle) * predicted_handle_radius,
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'wheel_radius': wheel_radius,
        'score': None,
        'count': None,
        'source': 'orbit_prediction_response_model',
        'radius': predicted_handle_radius,
        'mouse_target_angle_deg': round(math.degrees(target_angle), 3),
        'angle_response_gain': handle_angle_response_gain,
        'angle_deg': round(math.degrees(predicted_handle_angle), 3),
        'updated_at': time.time() if updated_at is None else updated_at,
    }


def tourbox_orbit_select_after_handle(
    after_raw_handle,
    predicted_after,
    *,
    wheel_geometry,
    min_detect_score,
):
    if after_raw_handle and wheel_geometry:
        after_raw_handle.update(wheel_geometry)
    detect_score = (
        float(after_raw_handle.get('score', 0.0))
        if after_raw_handle and after_raw_handle.get('score') is not None
        else 0.0
    )
    if after_raw_handle and detect_score >= min_detect_score:
        return {
            'after_raw_handle': after_raw_handle,
            'after_handle': after_raw_handle,
            'after_source': 'detected',
            'detect_score': detect_score,
        }
    return {
        'after_raw_handle': after_raw_handle,
        'after_handle': predicted_after,
        'after_source': 'prediction_low_score_fallback' if after_raw_handle else 'prediction_fallback',
        'detect_score': detect_score,
    }


def tourbox_orbit_after_drag_context(
    *,
    area,
    predicted_after,
    wheel_geometry,
    predictive_skip_after_detect,
    config_get,
    detect_raw_handle_fn,
    final_cursor_policy,
    original_cursor,
    arc_points,
):
    after_raw_handle = None
    if predictive_skip_after_detect:
        time.sleep(float(config_get('orbit_after_up_predictive_seconds', 0.01)))
        after_handle = predicted_after
        after_source = 'predictive_after'
    else:
        time.sleep(float(config_get('orbit_after_up_detect_seconds', 0.12)))
        after_raw_handle = detect_raw_handle_fn(area)
        after_selection = tourbox_orbit_select_after_handle(
            after_raw_handle,
            predicted_after,
            wheel_geometry=wheel_geometry,
            min_detect_score=float(config_get('orbit_after_detect_min_score', -999999.0)),
        )
        after_raw_handle = after_selection['after_raw_handle']
        after_handle = after_selection['after_handle']
        after_source = after_selection['after_source']

    final_cursor_target = tourbox_final_cursor_target(
        final_cursor_policy,
        after_handle,
        original_cursor,
        arc_points,
        end_source='arc_end',
    )
    return {
        'after_raw_handle': after_raw_handle,
        'after_handle': after_handle,
        'after_source': after_source,
        'final_cursor_target': final_cursor_target,
    }


def tourbox_orbit_start_plan(
    area,
    wheel_label,
    ticks,
    mode,
    *,
    predictive_cache_before,
    radius_target_before,
    detect_wheel_circle_fn,
    detect_raw_handle_fn,
    config_get,
):
    predictive_enabled = bool(config_get('orbit_predictive_enabled', False))
    predictive_key = str(wheel_label).lower()
    predictive_now = time.monotonic()
    predictive_cache_seconds = max(0.0, float(config_get('orbit_predictive_cache_seconds', 1.2)))
    predictive_center_tolerance = max(0.0, float(config_get('orbit_predictive_center_tolerance_px', 6.0)))
    start_detection = tourbox_orbit_start_detection_context(
        predictive_cache_before,
        predictive_enabled=predictive_enabled,
        predictive_key=predictive_key,
        predictive_now=predictive_now,
        predictive_cache_seconds=predictive_cache_seconds,
        predictive_center_tolerance=predictive_center_tolerance,
        area=area,
        detect_wheel_circle_fn=detect_wheel_circle_fn,
        detect_raw_handle_fn=detect_raw_handle_fn,
    )
    predictive_start_source = start_detection['predictive_start_source']
    wheel_geometry = start_detection['wheel_geometry']
    raw_handle = start_detection['raw_handle']
    if not raw_handle:
        return {
            'ok': False,
            'reason': 'handle_not_found',
        }

    geometry_context = tourbox_probe_wheel_geometry_context(raw_handle, wheel_geometry, area)
    center_x = geometry_context['center_x']
    center_y = geometry_context['center_y']
    wheel_radius = geometry_context['wheel_radius']
    start_x = float(raw_handle['x'])
    start_y = float(raw_handle['y'])
    handle_dx = start_x - center_x
    handle_dy = start_y - center_y
    handle_radius = math.hypot(handle_dx, handle_dy)
    min_handle_radius = max(1.0, float(config_get('orbit_min_handle_radius_px', 6.0)))
    if handle_radius < min_handle_radius:
        return {
            'ok': False,
            'reason': 'handle_too_close',
            'handle_radius': handle_radius,
            'min_handle_radius': min_handle_radius,
        }

    wheel_key = str(wheel_label).lower()
    target_now = time.monotonic()
    desired_radius = max(min_handle_radius, handle_radius)

    radius_target_enabled = bool(config_get('orbit_radius_target_enabled', True))
    radius_target_context = tourbox_orbit_radius_target_context(
        radius_target_before,
        radius_target_enabled=radius_target_enabled,
        wheel_key=wheel_key,
        target_now=target_now,
        predictive_start_source=predictive_start_source,
        handle_radius=handle_radius,
        min_handle_radius=min_handle_radius,
        center_x=center_x,
        center_y=center_y,
        config_get=config_get,
    )
    radius_target_source = radius_target_context['source']
    radius_target_before_value = radius_target_context['before']
    radius_target = radius_target_context['target_radius']
    target_seconds = radius_target_context['target_seconds']
    target_reset_px = radius_target_context['target_reset_px']

    start_angle = math.atan2(handle_dy, handle_dx)
    tick_context = tourbox_orbit_tick_context(
        ticks=ticks,
        start_angle=start_angle,
        desired_radius=desired_radius,
        min_handle_radius=min_handle_radius,
        config_get=config_get,
    )
    tick_direction = tick_context['tick_direction']
    tick_magnitude = tick_context['tick_magnitude']
    delta_degrees = tick_context['delta_degrees']
    delta_angle = tick_context['delta_angle']
    mouse_angle_gain = tick_context['mouse_angle_gain']
    mouse_delta_angle = tick_context['mouse_delta_angle']
    target_angle = tick_context['target_angle']
    handle_angle_response_gain = tick_context['handle_angle_response_gain']
    handle_radius_response_per_tick = tick_context['handle_radius_response_per_tick']
    predicted_handle_angle = tick_context['predicted_handle_angle']
    predicted_handle_radius = tick_context['predicted_handle_radius']

    arc_plan = tourbox_orbit_arc_motion_plan(
        mode=mode,
        start_x=start_x,
        start_y=start_y,
        center_x=center_x,
        center_y=center_y,
        start_angle=start_angle,
        handle_radius=handle_radius,
        desired_radius=desired_radius,
        wheel_radius=wheel_radius,
        min_handle_radius=min_handle_radius,
        radius_target_enabled=radius_target_enabled,
        radius_target=radius_target,
        mouse_delta_angle=mouse_delta_angle,
        config_get=config_get,
    )
    predicted_after = tourbox_orbit_predicted_after_handle(
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
        predicted_handle_angle=predicted_handle_angle,
        predicted_handle_radius=predicted_handle_radius,
        target_angle=target_angle,
        handle_angle_response_gain=handle_angle_response_gain,
    )

    return {
        'ok': True,
        'predictive_enabled': predictive_enabled,
        'predictive_key': predictive_key,
        'predictive_now': predictive_now,
        'predictive_cache_seconds': predictive_cache_seconds,
        'predictive_center_tolerance': predictive_center_tolerance,
        'start_detection': start_detection,
        'predictive_start_source': predictive_start_source,
        'wheel_geometry': wheel_geometry,
        'raw_handle': raw_handle,
        'geometry_context': geometry_context,
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
        'start_x': start_x,
        'start_y': start_y,
        'handle_dx': handle_dx,
        'handle_dy': handle_dy,
        'handle_radius': handle_radius,
        'min_handle_radius': min_handle_radius,
        'wheel_key': wheel_key,
        'target_now': target_now,
        'desired_radius': desired_radius,
        'radius_target_enabled': radius_target_enabled,
        'radius_target_context': radius_target_context,
        'radius_target_source': radius_target_source,
        'radius_target_before': radius_target_before_value,
        'radius_target': radius_target,
        'target_seconds': target_seconds,
        'target_reset_px': target_reset_px,
        'start_angle': start_angle,
        'tick_context': tick_context,
        'tick_direction': tick_direction,
        'tick_magnitude': tick_magnitude,
        'delta_degrees': delta_degrees,
        'delta_angle': delta_angle,
        'mouse_angle_gain': mouse_angle_gain,
        'mouse_delta_angle': mouse_delta_angle,
        'target_angle': target_angle,
        'handle_angle_response_gain': handle_angle_response_gain,
        'handle_radius_response_per_tick': handle_radius_response_per_tick,
        'predicted_handle_angle': predicted_handle_angle,
        'predicted_handle_radius': predicted_handle_radius,
        'arc_plan': arc_plan,
        'mode': arc_plan['mode'],
        'arc_source': arc_plan['arc_source'],
        'arc_radius': arc_plan['arc_radius'],
        'arc_end_radius': arc_plan['arc_end_radius'],
        'arc_steps': arc_plan['arc_steps'],
        'arc_points': arc_plan['arc_points'],
        'local_radius_bias': arc_plan['local_radius_bias'],
        'local_radius_bias_from_radius': arc_plan['local_radius_bias_from_radius'],
        'local_radius_bias_from_error': arc_plan['local_radius_bias_from_error'],
        'outer_edge_clamp_report': arc_plan['outer_edge_clamp_report'],
        'press_x': arc_plan['press_x'],
        'press_y': arc_plan['press_y'],
        'press_radius': arc_plan['press_radius'],
        'press_source': arc_plan['press_source'],
        'predicted_after': predicted_after,
    }


def tourbox_orbit_after_detection_policy(
    *,
    predictive_enabled,
    predictive_count_before,
    config_get,
):
    predictive_count_after = predictive_count_before + 1
    predictive_detect_every = max(0, int(config_get('orbit_predictive_detect_every', 0)))
    predictive_skip_after_detect = (
        predictive_enabled
        and bool(config_get('orbit_predictive_skip_after_detect', True))
        and (predictive_detect_every <= 0 or predictive_count_after % predictive_detect_every != 0)
    )
    return {
        'predictive_count_after': predictive_count_after,
        'predictive_detect_every': predictive_detect_every,
        'predictive_skip_after_detect': predictive_skip_after_detect,
    }


def tourbox_orbit_predictive_cache_payload(
    after_handle,
    *,
    predictive_key,
    center_x,
    center_y,
    wheel_radius,
    after_source,
    updated_at=None,
):
    return {
        'key': predictive_key,
        'x': float(after_handle['x']),
        'y': float(after_handle['y']),
        'wheel_center_x': float(center_x),
        'wheel_center_y': float(center_y),
        'wheel_radius': float(wheel_radius),
        'updated_at': time.monotonic() if updated_at is None else updated_at,
        'source': after_source,
    }


def tourbox_orbit_radius_target_payload(
    after_handle,
    *,
    wheel_key,
    radius_target,
    center_x,
    center_y,
    radius_target_source,
    updated_at=None,
):
    final_radius, _final_angle = tourbox_handle_polar(after_handle, center_x, center_y)
    return {
        'key': wheel_key,
        'target_radius': float(radius_target),
        'last_observed_radius': float(final_radius),
        'updated_at': time.monotonic() if updated_at is None else updated_at,
        'center_x': float(center_x),
        'center_y': float(center_y),
        'source': radius_target_source,
    }


def tourbox_orbit_after_state_payloads(
    after_handle,
    *,
    predictive_enabled,
    predictive_key,
    center_x,
    center_y,
    wheel_radius,
    after_source,
    radius_target_enabled,
    wheel_key,
    radius_target,
    radius_target_source,
):
    predictive_handle = None
    radius_target_after = None
    if predictive_enabled and after_handle:
        predictive_handle = tourbox_orbit_predictive_cache_payload(
            after_handle,
            predictive_key=predictive_key,
            center_x=center_x,
            center_y=center_y,
            wheel_radius=wheel_radius,
            after_source=after_source,
        )
    if radius_target_enabled and after_handle:
        radius_target_after = tourbox_orbit_radius_target_payload(
            after_handle,
            wheel_key=wheel_key,
            radius_target=radius_target,
            center_x=center_x,
            center_y=center_y,
            radius_target_source=radius_target_source,
        )
    return {
        'predictive_handle': predictive_handle,
        'radius_target_after': radius_target_after,
    }


def tourbox_final_cursor_target(
    policy,
    after_handle,
    original_cursor,
    end_points=None,
    *,
    end_source='line_end',
    missing_handle_source=None,
):
    normalized_policy = str(policy or '').lower()
    if normalized_policy in {'after_handle', 'white_point', 'handle'} and after_handle:
        return {
            'source': 'after_handle',
            'x': float(after_handle['x']),
            'y': float(after_handle['y']),
        }
    if normalized_policy in {'after_handle', 'white_point', 'handle'} and missing_handle_source:
        return {
            'source': missing_handle_source,
            'x': float(original_cursor[0]),
            'y': float(original_cursor[1]),
        }
    if normalized_policy in {'drag_end', 'line_end'} and end_points:
        return {
            'source': end_source,
            'x': float(end_points[-1][0]),
            'y': float(end_points[-1][1]),
        }
    if normalized_policy in {'original', 'restore_original'}:
        return {
            'source': 'original',
            'x': float(original_cursor[0]),
            'y': float(original_cursor[1]),
        }
    return None


def apply_tourbox_final_cursor_target(
    final_cursor_target,
    *,
    point_in_screen_bounds_fn,
    set_cursor_position_fn,
    record_fn,
):
    if not final_cursor_target:
        return False
    if not point_in_screen_bounds_fn(
        final_cursor_target['x'],
        final_cursor_target['y'],
        margin=-100000,
    ):
        return False

    ok = set_cursor_position_fn(
        int(round(final_cursor_target['x'])),
        int(round(final_cursor_target['y'])),
    )
    record_fn(
        f"cursor_after_drag_{final_cursor_target['source']}",
        final_cursor_target['x'],
        final_cursor_target['y'],
        ok,
    )
    return bool(ok)


def tourbox_perform_offscreen_drag(
    *,
    mode,
    start_x,
    start_y,
    line_points,
    send_absolute_move_fn,
    send_relative_move_fn,
    send_left_down_fn,
    send_left_up_fn,
    record_fn,
):
    ok = send_absolute_move_fn(start_x, start_y)
    record_fn('move_start_absolute', start_x, start_y, ok)
    time.sleep(0.03)
    ok = send_left_down_fn()
    record_fn('left_down', start_x, start_y, ok)
    time.sleep(0.045)

    if mode in {'offscreen', 'tourbox', 'relative_offscreen'}:
        ok = send_relative_move_fn(-10000, -10000)
        record_fn('move_relative_offscreen', -10000, -10000, ok)
        time.sleep(0.06)
    elif mode in {'absolute_offscreen', 'abs_offscreen'}:
        ok = send_absolute_move_fn(-10000, -10000)
        record_fn('move_absolute_offscreen', -10000, -10000, ok)
        time.sleep(0.06)

    delay = 0.055
    for point_x, point_y in line_points:
        ok = send_absolute_move_fn(point_x, point_y)
        record_fn('move_line_absolute', point_x, point_y, ok)
        time.sleep(delay)

    ok = send_left_up_fn()
    record_fn('left_up', line_points[-1][0], line_points[-1][1], ok)
    return ok


def tourbox_perform_orbit_drag(
    *,
    press_x,
    press_y,
    arc_points,
    config_get,
    send_absolute_move_fn,
    send_left_down_fn,
    send_left_up_fn,
    record_fn,
):
    ok = send_absolute_move_fn(press_x, press_y)
    record_fn('move_press_absolute', press_x, press_y, ok)
    time.sleep(float(config_get('orbit_press_settle_seconds', 0.03)))
    ok = send_left_down_fn()
    record_fn('left_down', press_x, press_y, ok)
    time.sleep(float(config_get('orbit_after_down_seconds', 0.045)))

    ok = send_absolute_move_fn(arc_points[0][0], arc_points[0][1])
    record_fn('move_orbit_arc_start', arc_points[0][0], arc_points[0][1], ok)
    time.sleep(float(config_get('orbit_arc_start_sleep_seconds', 0.04)))

    delay = float(config_get('orbit_move_delay_seconds', 0.045))
    for point_x, point_y in arc_points[1:]:
        ok = send_absolute_move_fn(point_x, point_y)
        record_fn('move_orbit_arc_absolute', point_x, point_y, ok)
        time.sleep(delay)

    ok = send_left_up_fn()
    record_fn('left_up', arc_points[-1][0], arc_points[-1][1], ok)
    return ok


__all__ = [
    'DIAGNOSTICS_DIR',
    'TOURBOX_PROBE_CONFIG_PATH',
    'apply_tourbox_final_cursor_target',
    'tourbox_center_bridge_handle',
    'tourbox_center_handle',
    'tourbox_arc_points',
    'tourbox_area_snapshot',
    'tourbox_canonical_diameter_axis',
    'tourbox_detection_suspicion_reason',
    'tourbox_exception_after_handle_context',
    'tourbox_handle_polar',
    'tourbox_offscreen_axis_selection',
    'tourbox_offscreen_center_bridge_projection',
    'tourbox_offscreen_line_plan',
    'tourbox_offscreen_probe_report',
    'tourbox_offscreen_probe_state_payload',
    'tourbox_offscreen_after_drag_context',
    'tourbox_offscreen_select_after_handle',
    'tourbox_offscreen_select_start_handle',
    'tourbox_offscreen_start_plan',
    'tourbox_offscreen_state_context',
    'tourbox_orbit_arc_motion_plan',
    'tourbox_orbit_after_detection_policy',
    'tourbox_orbit_after_drag_context',
    'tourbox_orbit_after_state_payloads',
    'tourbox_orbit_execute_split_plan',
    'tourbox_orbit_predictive_cache_payload',
    'tourbox_orbit_predictive_start_handle',
    'tourbox_orbit_predicted_after_handle',
    'tourbox_orbit_probe_report',
    'tourbox_orbit_radius_target_payload',
    'tourbox_radius_target_report',
    'tourbox_orbit_radius_target_context',
    'tourbox_orbit_select_after_handle',
    'tourbox_orbit_split_tick_plan',
    'tourbox_orbit_start_plan',
    'tourbox_orbit_start_detection_context',
    'tourbox_orbit_tick_context',
    'tourbox_point_list',
    'tourbox_perform_offscreen_drag',
    'tourbox_perform_orbit_drag',
    'tourbox_probe_exception_context',
    'tourbox_probe_config_getter',
    'tourbox_probe_wheel_geometry_context',
    'tourbox_probe_run_context',
    'TourBoxProbeConfigAccessor',
    'TourBoxProbeEventRecorder',
    'TourBoxMouseInput',
    'tourbox_predicted_handle',
    'tourbox_state_prediction_handle',
    'create_tourbox_probe_run_dir',
    'find_tourbox_probe_area',
    'load_tourbox_probe_config',
    'print_tourbox_offscreen_probe_result',
    'print_tourbox_orbit_probe_result',
    'tourbox_probe_prepare_area',
    'tourbox_final_cursor_target',
    'write_tourbox_probe_report',
]
