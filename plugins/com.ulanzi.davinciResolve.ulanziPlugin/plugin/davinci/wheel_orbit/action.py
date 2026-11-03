"""Closed-loop wheel orbit gesture orchestration."""

import time

from ..area_target_helpers import area_key
from ..wheel_diameter_geometry import wheel_diameter_mouse_start_point
from ..wheel_orbit_model import (
    wheel_orbit_detected_context,
    wheel_orbit_feedback_state,
    wheel_orbit_reuse_context,
    wheel_orbit_safe_radius,
    wheel_orbit_short_arc_plan,
)
from ..wheel_orbit_motion_execution import wheel_orbit_execute_motion
from .runtime import WheelOrbitRuntime


def _prepare(area, runtime):
    runtime.release_param_drag()
    runtime.release_wheel_drag()
    return area['name'], area_key(area), time.time()


def _start(area, area_name, target_key, now, runtime):
    orbit_context = wheel_orbit_reuse_context(
        runtime.state.wheel_orbit_state(),
        target_key,
        now,
    )
    if not orbit_context['reuse_orbit']:
        runtime.clear_wheel_orbit()
        handle = runtime.detect_handle(area_name)
        if not handle:
            print(f"[wheel-orbit] handle not found: {area_name}")
            runtime.clear_wheel_orbit()
            return None

        max_radius = wheel_orbit_safe_radius(area, handle)
        orbit_context = wheel_orbit_detected_context(area, handle, max_radius)
        orbit_context['reuse_orbit'] = False
        orbit_context['reuse_dragging'] = False

    if not orbit_context['reuse_dragging']:
        start_mouse_x, start_mouse_y = wheel_diameter_mouse_start_point(
            orbit_context['center_x'],
            orbit_context['center_y'],
            orbit_context['start_angle'],
            orbit_context['locked_radius'],
            orbit_context['start_x'],
            orbit_context['start_y'],
            orbit_context['wheel_radius_value'] or orbit_context['locked_radius'],
        )
        orbit_context = dict(orbit_context)
        orbit_context['start_mouse_x'] = start_mouse_x
        orbit_context['start_mouse_y'] = start_mouse_y
    return orbit_context


def _plan(orbit_context, ticks, sensitivity):
    return wheel_orbit_short_arc_plan(
        orbit_context['center_x'],
        orbit_context['center_y'],
        orbit_context['start_x'],
        orbit_context['start_y'],
        orbit_context['start_angle'],
        orbit_context['locked_radius'],
        ticks,
        sensitivity,
    )


def _begin_session(
    area,
    area_name,
    target_key,
    orbit_context,
    runtime,
):
    if orbit_context['reuse_dragging']:
        runtime.state.update_wheel_orbit_motion(True, updated_at=time.time())
        return True

    if not runtime.mouse_drag_begin(
        orbit_context['start_mouse_x'],
        orbit_context['start_mouse_y'],
    ):
        runtime.clear_wheel_orbit()
        return False

    runtime.state.start_wheel_orbit_session(
        target_key,
        area_name,
        area,
        orbit_context['center_x'],
        orbit_context['center_y'],
        orbit_context['locked_radius'],
        orbit_context['actual_radius'],
        orbit_context['wheel_radius_value'],
        orbit_context['start_angle'],
        orbit_context['start_x'],
        orbit_context['start_y'],
        orbit_context['start_mouse_x'],
        orbit_context['start_mouse_y'],
        orbit_context['segment_count'],
        updated_at=time.time(),
    )
    return True


def _execute_motion(
    area,
    area_name,
    target_key,
    ticks,
    orbit_context,
    orbit_plan,
    runtime,
):
    return wheel_orbit_execute_motion(
        area,
        area_name,
        target_key,
        ticks,
        orbit_context,
        orbit_plan,
        runtime.mouse_drag_move_path,
        runtime.mouse_drag_move_by_path,
        runtime.get_cursor_position,
        runtime.detect_raw_handle,
        runtime.release_wheel_orbit_drag,
        runtime.state.wheel_orbit_state,
        lambda: runtime.state.update_wheel_orbit_motion(False),
    )


def _finish(area, area_name, orbit_context, orbit_plan, motion_result, runtime):
    feedback_state = wheel_orbit_feedback_state(
        orbit_context['center_x'],
        orbit_context['center_y'],
        orbit_context['locked_radius'],
        orbit_context['actual_radius'],
        orbit_plan['target_angle'],
        orbit_plan['target_x'],
        orbit_plan['target_y'],
        motion_result['feedback_handle'],
    )
    updated_at = time.time()
    runtime.state.commit_wheel_orbit_feedback_state(
        feedback_state['state_angle'],
        feedback_state['state_handle_x'],
        feedback_state['state_handle_y'],
        motion_result['cursor_end_x'],
        motion_result['cursor_end_y'],
        feedback_state['state_actual_radius'],
        orbit_context['segment_count'] + 1,
        updated_at=updated_at,
    )
    runtime.state.commit_wheel_predicted_handle(
        area,
        area_name,
        orbit_context['center_x'],
        orbit_context['center_y'],
        orbit_context['wheel_radius_value'],
        feedback_state['output_handle_x'],
        feedback_state['output_handle_y'],
        feedback_state['state_angle'],
        orbit_context['locked_radius'],
        updated_at=updated_at,
    )


def handle_wheel_orbit_closed_loop(
    area,
    ticks,
    runtime: WheelOrbitRuntime,
    sensitivity,
):
    if ticks == 0:
        return False

    area_name, target_key, now = _prepare(area, runtime)
    orbit_context = _start(area, area_name, target_key, now, runtime)
    if not orbit_context:
        return False
    orbit_plan = _plan(orbit_context, ticks, sensitivity)
    if not _begin_session(
        area,
        area_name,
        target_key,
        orbit_context,
        runtime,
    ):
        return False

    motion_result = _execute_motion(
        area,
        area_name,
        target_key,
        ticks,
        orbit_context,
        orbit_plan,
        runtime,
    )
    _finish(
        area,
        area_name,
        orbit_context,
        orbit_plan,
        motion_result,
        runtime,
    )
    return motion_result['moved']


__all__ = ['handle_wheel_orbit_closed_loop']
