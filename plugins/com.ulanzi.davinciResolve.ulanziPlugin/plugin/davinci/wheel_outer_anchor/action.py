"""Outer-anchor gesture orchestration."""

import time

from ..area_target_helpers import area_key
from ..wheel_outer_anchor_drag_execution import wheel_outer_anchor_execute_drag
from ..wheel_outer_anchor_feedback_context import wheel_outer_anchor_feedback_context
from ..wheel_outer_anchor_preview_context import wheel_outer_anchor_preview_context
from ..wheel_outer_anchor_start_context import wheel_outer_anchor_start_context
from .runtime import WheelOuterAnchorRuntime


def _prepare(runtime):
    runtime.clear_wheel_orbit()
    previous_diameter_state = runtime.state.wheel_diameter_state()
    runtime.state.clear_wheel_diameter_state()
    runtime.release_param_drag()
    runtime.release_wheel_drag()
    return previous_diameter_state


def _start(area, previous_diameter_state, runtime):
    area_name = area['name']
    target_key = area_key(area)
    state = runtime.state
    start_context = wheel_outer_anchor_start_context(
        area,
        area_name,
        target_key,
        previous_diameter_state,
        time.time(),
        runtime.detect_wheel_circle_in_area,
        runtime.detect_handle,
        runtime.detect_raw_handle,
        state.wheel_anchor_state,
        state.seed_wheel_anchor_state_from_overlay,
        state.wheel_handle_for_area,
        state.clear_wheel_anchor_state,
        state.overlay_state,
        runtime.debug_slow,
    )
    if not start_context:
        return None
    return area_name, target_key, start_context


def _preview(
    area,
    area_name,
    target_key,
    ticks,
    start_context,
    runtime,
    sensitivity,
):
    preview_context = wheel_outer_anchor_preview_context(
        area,
        area_name,
        target_key,
        ticks,
        start_context['center_x'],
        start_context['center_y'],
        start_context.get('visual_center_x'),
        start_context.get('visual_center_y'),
        start_context['wheel_radius'],
        start_context['visual_radius'],
        start_context['handle_radius'],
        start_context['actual_radius'],
        start_context['start_angle'],
        start_context['state'],
        start_context['reuse_state'],
        start_context['previous'],
        start_context['force_fresh_handle'],
        start_context['previous_from_diameter'],
        start_context['no_progress_count'],
        lambda center_x, center_y, wheel_radius: runtime.state.wheel_state_for_area(
            area,
            center_x,
            center_y,
            wheel_radius,
        ),
        runtime.state.commit_wheel_anchor_state,
        sensitivity,
        runtime.pump_overlay_messages,
    )
    target_plan = preview_context['target_plan']
    preview = dict(start_context)
    preview.update({
        'stored_effective_max_radius': preview_context['stored_effective_max_radius'],
        'target_plan': target_plan,
        'delta_angle': target_plan['delta_angle'],
        'state_angle': target_plan['state_angle'],
        'target_x': target_plan['target_x'],
        'target_y': target_plan['target_y'],
        'adaptive_degrees_per_tick': preview_context['adaptive_degrees_per_tick'],
        'adaptive_tick_units': preview_context['adaptive_tick_units'],
        'outer_control_radius': preview_context['outer_control_radius'],
        'outer_x': preview_context['outer_x'],
        'outer_y': preview_context['outer_y'],
    })
    return preview


def _drag(area, area_name, ticks, preview, runtime, sensitivity):
    return wheel_outer_anchor_execute_drag(
        area,
        area_name,
        ticks,
        preview['source'],
        preview['start_x'],
        preview['start_y'],
        preview['start_angle'],
        preview['state_angle'],
        preview['delta_angle'],
        preview['handle_radius'],
        preview['actual_radius'],
        preview['no_progress_count'],
        preview['visual_radius'],
        preview['outer_control_radius'],
        preview['target_x'],
        preview['target_y'],
        preview['outer_x'],
        preview['outer_y'],
        runtime.mouse_drag_begin,
        runtime.mouse_drag_move_absolute_path,
        runtime.mouse_drag_end,
        runtime.get_cursor_position,
        runtime.detect_raw_handle,
        sensitivity,
        runtime.set_cursor_position,
        runtime.debug_slow,
    )


def _finish(area, area_name, target_key, preview, drag_result, runtime):
    feedback = wheel_outer_anchor_feedback_context(
        area,
        area_name,
        preview['center_x'],
        preview['center_y'],
        preview['start_angle'],
        preview['state_angle'],
        preview['handle_radius'],
        preview['actual_radius'],
        preview['no_progress_count'],
        drag_result['near_center_anchor'],
        drag_result['feedback_handle'],
        preview['visual_radius'],
        preview['wheel_radius'],
        preview['outer_control_radius'],
        preview['outer_x'],
        preview['outer_y'],
        preview['adaptive_degrees_per_tick'],
        preview['adaptive_tick_units'],
        preview['source'],
        runtime.debug_slow,
    )
    runtime.state.commit_wheel_anchor_state(
        area,
        area_name,
        target_key,
        preview['center_x'],
        preview['center_y'],
        preview['wheel_radius'],
        preview['visual_radius'],
        feedback['outer_control_radius'],
        feedback['outer_x'],
        feedback['outer_y'],
        feedback['state_angle'],
        feedback['state_handle_radius'],
        feedback['state_actual_radius'],
        feedback['state_handle_x'],
        feedback['state_handle_y'],
        preview['stored_effective_max_radius'],
        no_progress_count=feedback['next_no_progress_count'],
        adaptive_degrees_per_tick=feedback['adaptive_degrees_per_tick'],
        adaptive_handle_radius=feedback['state_handle_radius'],
        force_fresh_handle=feedback['force_fresh_handle'],
        last_detected_handle=drag_result['feedback_handle'],
        visual_center_x=preview.get('visual_center_x'),
        visual_center_y=preview.get('visual_center_y'),
        commit_handle=feedback['feedback_accepted'],
        store_source='outer_anchor',
        mark_recent=True,
        lock_target=True,
        updated_at=time.time(),
    )
    return feedback


def handle_wheel_outer_anchor_rotate(
    area,
    ticks,
    runtime: WheelOuterAnchorRuntime,
    sensitivity,
):
    if ticks == 0:
        return False

    previous_diameter_state = _prepare(runtime)
    start = _start(area, previous_diameter_state, runtime)
    if not start:
        return False
    area_name, target_key, start_context = start
    preview = _preview(
        area,
        area_name,
        target_key,
        ticks,
        start_context,
        runtime,
        sensitivity,
    )
    drag_result = _drag(
        area,
        area_name,
        ticks,
        preview,
        runtime,
        sensitivity,
    )
    if not drag_result['ok']:
        return False
    _finish(area, area_name, target_key, preview, drag_result, runtime)
    return drag_result['moved']


__all__ = ['handle_wheel_outer_anchor_rotate']
