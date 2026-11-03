"""Diagnostic TourBox probe runners kept out of the main action module."""

from ..area_target_helpers import area_key, area_label
from ..config import TOURBOX_PROBE_EXTRA_INFO
from .tourbox_probe import (
    apply_tourbox_final_cursor_target,
    tourbox_offscreen_after_drag_context,
    tourbox_offscreen_probe_state_payload,
    tourbox_offscreen_start_plan,
    tourbox_orbit_after_detection_policy,
    tourbox_orbit_after_drag_context,
    tourbox_orbit_after_state_payloads,
    tourbox_orbit_execute_split_plan,
    tourbox_orbit_split_tick_plan,
    tourbox_orbit_start_plan,
    tourbox_perform_offscreen_drag,
    tourbox_perform_orbit_drag,
    tourbox_probe_exception_context,
    tourbox_probe_prepare_area,
)
from .tourbox_probe_runtime import tourbox_probe_config_getter, tourbox_probe_run_context
from .tourbox_probe_reports import (
    print_tourbox_offscreen_probe_result,
    print_tourbox_orbit_probe_result,
    tourbox_offscreen_probe_report,
    tourbox_orbit_probe_report,
    write_tourbox_probe_report,
)


def run_tourbox_offscreen_probe_action(
    manager,
    *,
    ticks=1,
    mode='offscreen',
    wheel_name='Offset',
    win32_input_available=False,
    detect_wheel_circle_in_area_fn,
    get_cursor_position_fn,
    point_in_screen_bounds_fn,
    set_cursor_position_fn,
    send_absolute_move_fn,
    send_relative_move_fn,
    send_left_down_fn,
    send_left_up_fn,
    recent_wheel_area_fn,
    release_param_drag_fn,
    release_wheel_drag_fn,
    release_wheel_orbit_drag_fn,
    detect_raw_handle_fn,
):
    if not win32_input_available:
        print("tourbox probe requires Windows Win32 input")
        return False

    probe_config_get = tourbox_probe_config_getter()

    area = tourbox_probe_prepare_area(
        manager.areas,
        manager.current_hover_area,
        recent_wheel_area_fn,
        wheel_name,
        release_param_drag_fn=release_param_drag_fn,
        release_wheel_drag_fn=release_wheel_drag_fn,
        release_wheel_orbit_drag_fn=release_wheel_orbit_drag_fn,
    )
    if area is None:
        print(f"tourbox probe: wheel not found ({wheel_name})")
        return False

    target_key = area_key(area)
    start_plan = tourbox_offscreen_start_plan(
        area,
        target_key,
        manager._tourbox_probe_state,
        ticks,
        detect_wheel_circle_fn=detect_wheel_circle_in_area_fn,
        detect_raw_handle_fn=detect_raw_handle_fn,
        config_get=probe_config_get,
    )
    if not start_plan['ok']:
        print(f"tourbox probe: handle not found ({area_label(area)})")
        return False

    wheel_geometry = start_plan['wheel_geometry']
    probe_state = start_plan['probe_state']
    axis_lock_seconds = start_plan['axis_lock_seconds']
    center_bridge_seconds = start_plan['center_bridge_seconds']
    raw_handle = start_plan['raw_handle']
    center_x = start_plan['center_x']
    center_y = start_plan['center_y']
    axis_mode = start_plan['axis_mode']
    prediction_enabled = start_plan['prediction_enabled']
    center_bridge_enabled = start_plan['center_bridge_enabled']
    before_suspicion_reason = start_plan['before_suspicion_reason']
    handle = start_plan['handle']
    handle_source = start_plan['handle_source']
    start_x = start_plan['start_x']
    start_y = start_plan['start_y']
    direction = start_plan['direction']
    handle_radius = start_plan['handle_radius']
    axis_angle = start_plan['axis_angle']
    axis_source = start_plan['axis_source']
    bridge_info = start_plan['bridge_info']
    start_signed_axis = start_plan['start_signed_axis']
    start_perpendicular_axis = start_plan['start_perpendicular_axis']
    line_distance_requested_px = start_plan['line_distance_requested_px']
    line_distance_px = start_plan['line_distance_px']
    guard_info = start_plan['guard_info']
    line_steps = start_plan['line_steps']
    line_points = start_plan['line_points']
    predicted_after = start_plan['predicted_after']

    mode = str(mode or 'offscreen').lower()
    run_context = tourbox_probe_run_context(
        'tourbox_probe',
        config_get=probe_config_get,
        get_cursor_position_fn=get_cursor_position_fn,
    )
    original_cursor = run_context['original_cursor']
    final_cursor_policy = run_context['final_cursor_policy']
    final_cursor_target = run_context['final_cursor_target']
    run_dir = run_context['run_dir']
    events = run_context['events']
    record = run_context['record']

    try:
        tourbox_perform_offscreen_drag(
            mode=mode,
            start_x=start_x,
            start_y=start_y,
            line_points=line_points,
            send_absolute_move_fn=send_absolute_move_fn,
            send_relative_move_fn=send_relative_move_fn,
            send_left_down_fn=send_left_down_fn,
            send_left_up_fn=send_left_up_fn,
            record_fn=record,
        )
        after_context = tourbox_offscreen_after_drag_context(
            area=area,
            predicted_after=predicted_after,
            wheel_geometry=wheel_geometry,
            center_x=center_x,
            center_y=center_y,
            prediction_enabled=prediction_enabled,
            center_bridge_enabled=center_bridge_enabled,
            config_get=probe_config_get,
            detect_raw_handle_fn=detect_raw_handle_fn,
            final_cursor_policy=final_cursor_policy,
            original_cursor=original_cursor,
            line_points=line_points,
        )
        after_raw_handle = after_context['after_raw_handle']
        after_suspicion_reason = after_context['after_suspicion_reason']
        after_handle = after_context['after_handle']
        after_source = after_context['after_source']
        final_cursor_target = after_context['final_cursor_target']

        apply_tourbox_final_cursor_target(
            final_cursor_target,
            point_in_screen_bounds_fn=point_in_screen_bounds_fn,
            set_cursor_position_fn=set_cursor_position_fn,
            record_fn=record,
        )
    except Exception as exc:
        exception_context = tourbox_probe_exception_context(
            area=area,
            send_left_up_fn=send_left_up_fn,
            detect_raw_handle_fn=detect_raw_handle_fn,
            record_fn=record,
        )
        after_raw_handle = exception_context['after_raw_handle']
        after_handle = exception_context['after_handle']
        after_source = exception_context['after_source']
        after_suspicion_reason = exception_context['after_suspicion_reason']
        print(f"tourbox probe failed: {exc}")
        result_error = repr(exc)
    else:
        result_error = None

    report = tourbox_offscreen_probe_report(
        mode=mode,
        wheel_label=area_label(area),
        ticks=ticks,
        direction=direction,
        invert_tick_direction=bool(probe_config_get('invert_tick_direction', False)),
        extra_info=TOURBOX_PROBE_EXTRA_INFO,
        run_dir=run_dir,
        original_cursor=original_cursor,
        final_cursor_policy=final_cursor_policy,
        final_cursor_target=final_cursor_target,
        area=area,
        handle=handle,
        raw_handle=raw_handle,
        handle_source=handle_source,
        before_suspicion_reason=before_suspicion_reason,
        after_handle=after_handle,
        after_raw_handle=after_raw_handle,
        after_source=after_source,
        after_suspicion_reason=after_suspicion_reason,
        predicted_after=predicted_after,
        axis_angle=axis_angle,
        axis_mode=axis_mode,
        axis_source=axis_source,
        axis_lock_seconds=axis_lock_seconds,
        center_bridge_seconds=center_bridge_seconds,
        probe_state=probe_state,
        bridge_info=bridge_info,
        start_signed_axis=start_signed_axis,
        start_perpendicular_axis=start_perpendicular_axis,
        handle_radius=handle_radius,
        line_distance_requested_px=line_distance_requested_px,
        line_distance_px=line_distance_px,
        line_steps=line_steps,
        guard_info=guard_info,
        line_points=line_points,
        events=events,
        result_error=result_error,
    )
    report_path = write_tourbox_probe_report(run_dir, report)

    print_tourbox_offscreen_probe_result(
        mode,
        area_label(area),
        handle,
        after_handle,
        report_path,
    )
    probe_state_after = tourbox_offscreen_probe_state_payload(
        center_bridge_enabled=center_bridge_enabled,
        result_error=result_error,
        bridge_info=bridge_info,
        before_suspicion_reason=before_suspicion_reason,
        after_suspicion_reason=after_suspicion_reason,
        axis_mode=axis_mode,
        target_key=target_key,
        axis_angle=axis_angle,
        after_handle=after_handle,
        predicted_after=predicted_after,
        axis_source=axis_source,
    )
    if probe_state_after:
        manager._tourbox_probe_state = probe_state_after
    return result_error is None


def run_tourbox_orbit_probe_action(
    manager,
    *,
    ticks=1,
    mode='local_arc',
    wheel_name='Offset',
    win32_input_available=False,
    detect_wheel_circle_in_area_fn,
    get_cursor_position_fn,
    point_in_screen_bounds_fn,
    set_cursor_position_fn,
    send_absolute_move_fn,
    send_left_down_fn,
    send_left_up_fn,
    recent_wheel_area_fn,
    release_param_drag_fn,
    release_wheel_drag_fn,
    release_wheel_orbit_drag_fn,
    detect_raw_handle_fn,
):
    if not win32_input_available:
        print("tourbox orbit probe requires Windows Win32 input")
        return False

    probe_config_get = tourbox_probe_config_getter()

    split_plan = tourbox_orbit_split_tick_plan(ticks, config_get=probe_config_get)
    split_result = tourbox_orbit_execute_split_plan(
        split_plan,
        manager.run_tourbox_orbit_probe,
        mode=mode,
        wheel_name=wheel_name,
    )
    if split_result is not None:
        return split_result

    area = tourbox_probe_prepare_area(
        manager.areas,
        manager.current_hover_area,
        recent_wheel_area_fn,
        wheel_name,
        release_param_drag_fn=release_param_drag_fn,
        release_wheel_drag_fn=release_wheel_drag_fn,
        release_wheel_orbit_drag_fn=release_wheel_orbit_drag_fn,
    )
    if area is None:
        print(f"tourbox orbit probe: wheel not found ({wheel_name})")
        return False

    wheel_label = area_label(area)
    predictive_cache_before = getattr(manager, '_tourbox_orbit_predictive_handle', None)
    orbit_start = tourbox_orbit_start_plan(
        area=area,
        wheel_label=wheel_label,
        ticks=ticks,
        mode=mode,
        predictive_cache_before=predictive_cache_before,
        radius_target_before=getattr(manager, '_tourbox_orbit_radius_target', None),
        detect_wheel_circle_fn=detect_wheel_circle_in_area_fn,
        detect_raw_handle_fn=detect_raw_handle_fn,
        config_get=probe_config_get,
    )
    if not orbit_start['ok']:
        if orbit_start['reason'] == 'handle_too_close':
            print(
                f"tourbox orbit probe: handle too close to center "
                f"radius={orbit_start['handle_radius']:.1f} "
                f"min={orbit_start['min_handle_radius']:.1f}"
            )
            return False
        print(f"tourbox orbit probe: handle not found ({wheel_label})")
        return False

    radius_target_after = None
    predictive_enabled = orbit_start['predictive_enabled']
    predictive_key = orbit_start['predictive_key']
    predictive_cache_seconds = orbit_start['predictive_cache_seconds']
    predictive_start_source = orbit_start['predictive_start_source']
    wheel_geometry = orbit_start['wheel_geometry']
    raw_handle = orbit_start['raw_handle']
    center_x = orbit_start['center_x']
    center_y = orbit_start['center_y']
    wheel_radius = orbit_start['wheel_radius']
    handle_radius = orbit_start['handle_radius']
    wheel_key = orbit_start['wheel_key']
    target_now = orbit_start['target_now']
    desired_radius = orbit_start['desired_radius']
    radius_target_enabled = orbit_start['radius_target_enabled']
    radius_target_source = orbit_start['radius_target_source']
    radius_target_before = orbit_start['radius_target_before']
    radius_target = orbit_start['radius_target']
    target_seconds = orbit_start['target_seconds']
    target_reset_px = orbit_start['target_reset_px']
    start_angle = orbit_start['start_angle']
    tick_direction = orbit_start['tick_direction']
    delta_degrees = orbit_start['delta_degrees']
    mouse_angle_gain = orbit_start['mouse_angle_gain']
    mouse_delta_angle = orbit_start['mouse_delta_angle']
    target_angle = orbit_start['target_angle']
    handle_angle_response_gain = orbit_start['handle_angle_response_gain']
    handle_radius_response_per_tick = orbit_start['handle_radius_response_per_tick']
    mode = orbit_start['mode']
    arc_source = orbit_start['arc_source']
    arc_radius = orbit_start['arc_radius']
    arc_end_radius = orbit_start['arc_end_radius']
    arc_steps = orbit_start['arc_steps']
    arc_points = orbit_start['arc_points']
    local_radius_bias = orbit_start['local_radius_bias']
    local_radius_bias_from_radius = orbit_start['local_radius_bias_from_radius']
    local_radius_bias_from_error = orbit_start['local_radius_bias_from_error']
    outer_edge_clamp_report = orbit_start['outer_edge_clamp_report']
    press_x = orbit_start['press_x']
    press_y = orbit_start['press_y']
    press_radius = orbit_start['press_radius']
    press_source = orbit_start['press_source']
    predicted_after = orbit_start['predicted_after']

    run_context = tourbox_probe_run_context(
        'tourbox_orbit_probe',
        config_get=probe_config_get,
        get_cursor_position_fn=get_cursor_position_fn,
    )
    original_cursor = run_context['original_cursor']
    final_cursor_policy = run_context['final_cursor_policy']
    final_cursor_target = run_context['final_cursor_target']
    run_dir = run_context['run_dir']
    events = run_context['events']
    record = run_context['record']

    after_raw_handle = None
    after_handle = None
    after_source = None
    predictive_count_before = int(getattr(manager, '_tourbox_orbit_predictive_count', 0) or 0)
    after_detection_policy = tourbox_orbit_after_detection_policy(
        predictive_enabled=predictive_enabled,
        predictive_count_before=predictive_count_before,
        config_get=probe_config_get,
    )
    predictive_count_after = after_detection_policy['predictive_count_after']
    predictive_detect_every = after_detection_policy['predictive_detect_every']
    predictive_skip_after_detect = after_detection_policy['predictive_skip_after_detect']
    result_error = None
    try:
        tourbox_perform_orbit_drag(
            press_x=press_x,
            press_y=press_y,
            arc_points=arc_points,
            config_get=probe_config_get,
            send_absolute_move_fn=send_absolute_move_fn,
            send_left_down_fn=send_left_down_fn,
            send_left_up_fn=send_left_up_fn,
            record_fn=record,
        )
        after_context = tourbox_orbit_after_drag_context(
            area=area,
            predicted_after=predicted_after,
            wheel_geometry=wheel_geometry,
            predictive_skip_after_detect=predictive_skip_after_detect,
            config_get=probe_config_get,
            detect_raw_handle_fn=detect_raw_handle_fn,
            final_cursor_policy=final_cursor_policy,
            original_cursor=original_cursor,
            arc_points=arc_points,
        )
        after_raw_handle = after_context['after_raw_handle']
        after_handle = after_context['after_handle']
        after_source = after_context['after_source']

        after_state_payloads = tourbox_orbit_after_state_payloads(
            after_handle,
            predictive_enabled=predictive_enabled,
            predictive_key=predictive_key,
            center_x=center_x,
            center_y=center_y,
            wheel_radius=wheel_radius,
            after_source=after_source,
            radius_target_enabled=radius_target_enabled,
            wheel_key=wheel_key,
            radius_target=radius_target,
            radius_target_source=radius_target_source,
        )
        predictive_handle_after = after_state_payloads['predictive_handle']
        if predictive_handle_after:
            manager._tourbox_orbit_predictive_count = predictive_count_after
            manager._tourbox_orbit_predictive_handle = predictive_handle_after

        radius_target_after = after_state_payloads['radius_target_after']
        if radius_target_after:
            manager._tourbox_orbit_radius_target = radius_target_after

        final_cursor_target = after_context['final_cursor_target']

        apply_tourbox_final_cursor_target(
            final_cursor_target,
            point_in_screen_bounds_fn=point_in_screen_bounds_fn,
            set_cursor_position_fn=set_cursor_position_fn,
            record_fn=record,
        )
    except Exception as exc:
        exception_context = tourbox_probe_exception_context(
            area=area,
            send_left_up_fn=send_left_up_fn,
            detect_raw_handle_fn=detect_raw_handle_fn,
            record_fn=record,
        )
        after_raw_handle = exception_context['after_raw_handle']
        after_handle = exception_context['after_handle']
        after_source = exception_context['after_source']
        print(f"tourbox orbit probe failed: {exc}")
        result_error = repr(exc)

    report = tourbox_orbit_probe_report(
        mode=mode,
        arc_source=arc_source,
        wheel_label=area_label(area),
        ticks=ticks,
        tick_direction=tick_direction,
        orbit_invert_tick_direction=bool(probe_config_get('orbit_invert_tick_direction', False)),
        delta_degrees=delta_degrees,
        mouse_delta_angle=mouse_delta_angle,
        mouse_angle_gain=mouse_angle_gain,
        predictive_enabled=predictive_enabled,
        predictive_start_source=predictive_start_source,
        predictive_skip_after_detect=predictive_skip_after_detect,
        predictive_count_before=predictive_count_before,
        predictive_count_after=predictive_count_after,
        predictive_detect_every=predictive_detect_every,
        predictive_cache_seconds=predictive_cache_seconds,
        handle_angle_response_gain=handle_angle_response_gain,
        handle_radius_response_per_tick=handle_radius_response_per_tick,
        extra_info=TOURBOX_PROBE_EXTRA_INFO,
        run_dir=run_dir,
        original_cursor=original_cursor,
        final_cursor_policy=final_cursor_policy,
        final_cursor_target=final_cursor_target,
        area=area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
        raw_handle=raw_handle,
        after_handle=after_handle,
        after_raw_handle=after_raw_handle,
        after_source=after_source,
        predicted_after=predicted_after,
        start_angle=start_angle,
        target_angle=target_angle,
        handle_radius=handle_radius,
        desired_radius=desired_radius,
        press_source=press_source,
        press_x=press_x,
        press_y=press_y,
        press_radius=press_radius,
        radius_target_enabled=radius_target_enabled,
        radius_target_source=radius_target_source,
        radius_target=radius_target,
        target_seconds=target_seconds,
        target_reset_px=target_reset_px,
        radius_target_before=radius_target_before,
        radius_target_after=radius_target_after,
        target_now=target_now,
        arc_radius=arc_radius,
        arc_end_radius=arc_end_radius,
        local_radius_bias=local_radius_bias,
        local_radius_bias_from_radius=local_radius_bias_from_radius,
        local_radius_bias_from_error=local_radius_bias_from_error,
        outer_edge_clamp_report=outer_edge_clamp_report,
        arc_steps=arc_steps,
        arc_points=arc_points,
        events=events,
        result_error=result_error,
    )
    report_path = write_tourbox_probe_report(run_dir, report)

    print_tourbox_orbit_probe_result(
        mode,
        area_label(area),
        start_angle,
        target_angle,
        raw_handle,
        after_handle,
        report_path,
    )
    return result_error is None


__all__ = [
    'run_tourbox_offscreen_probe_action',
    'run_tourbox_orbit_probe_action',
]
