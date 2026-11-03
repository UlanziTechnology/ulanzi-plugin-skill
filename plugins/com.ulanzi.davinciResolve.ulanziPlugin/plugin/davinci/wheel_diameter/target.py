"""Target calculation, preview commit, and mouse-plan assembly."""

import time

from ..wheel_diameter_target_logic import (
    wheel_diameter_target_commit_context,
    wheel_diameter_target_context,
)
from ..wheel_state_diameter_payloads import wheel_diameter_drag_update_payload
from .mouse_plan import build_diameter_mouse_plan


def _update_drag(active_context, target_plan, commit_context):
    active_context['drag'].update(wheel_diameter_drag_update_payload(
        target_plan['target_x'],
        target_plan['target_y'],
        active_context['axis_angle'],
        target_plan['target_signed_radius'],
        active_context['effective_max_radius'],
        active_context['outer_control_radius'],
        updated_at=commit_context['updated_at'],
    ))


def _commit_noop_target(
    area,
    preparation,
    active_context,
    target_plan,
    commit_context,
    runtime,
):
    state = runtime.state
    state.commit_wheel_diameter_state(
        area,
        preparation.area_name,
        preparation.target_key,
        active_context['center_x'],
        active_context['center_y'],
        active_context['wheel_radius'],
        active_context['visual_radius'],
        active_context['axis_angle'],
        commit_context['signed_radius'],
        active_context['max_radius'],
        active_context['effective_max_radius'],
        active_context['outer_control_radius'],
        commit_context['outer_x'],
        commit_context['outer_y'],
        commit_context['control_angle'],
        commit_context['x'],
        commit_context['y'],
        commit_context['state_angle'],
        store_source=commit_context['store_source'],
        mark_recent=True,
        updated_at=commit_context['updated_at'],
    )
    _update_drag(active_context, target_plan, commit_context)
    state.set_wheel_diameter_axis_lock(
        area,
        active_context['center_x'],
        active_context['center_y'],
        active_context['axis_angle'],
        target_plan['target_signed_radius'],
        source='diameter_noop',
        allow_center=True,
    )
    runtime.release_wheel_drag()
    return {'done': True}


def _commit_preview_target(
    area,
    preparation,
    active_context,
    target_plan,
    commit_context,
    runtime,
):
    state = runtime.state
    state.commit_wheel_diameter_state(
        area,
        preparation.area_name,
        preparation.target_key,
        active_context['center_x'],
        active_context['center_y'],
        active_context['wheel_radius'],
        active_context['visual_radius'],
        active_context['axis_angle'],
        commit_context['signed_radius'],
        active_context['max_radius'],
        active_context['effective_max_radius'],
        active_context['outer_control_radius'],
        commit_context['outer_x'],
        commit_context['outer_y'],
        commit_context['control_angle'],
        commit_context['x'],
        commit_context['y'],
        commit_context['state_angle'],
        state_source=commit_context['state_source'],
        handle_source=commit_context['handle_source'],
        store_source=commit_context['store_source'],
        handle_visual_radius=active_context['visual_radius'],
        updated_at=commit_context['updated_at'],
    )
    _update_drag(active_context, target_plan, commit_context)
    state.set_wheel_diameter_axis_lock(
        area,
        active_context['center_x'],
        active_context['center_y'],
        active_context['axis_angle'],
        target_plan['target_signed_radius'],
        source='diameter_preview',
        allow_center=True,
    )
    state.mark_recent_wheel_area(area, updated_at=commit_context['updated_at'])
    state.refresh_wheel_overlay(area)
    if runtime.pump_overlay_messages:
        runtime.pump_overlay_messages()
    return {'done': False}


def _commit_target(
    area,
    preparation,
    active_context,
    target_plan,
    commit_context,
    runtime,
):
    if commit_context['kind'] == 'noop':
        return _commit_noop_target(
            area,
            preparation,
            active_context,
            target_plan,
            commit_context,
            runtime,
        )
    return _commit_preview_target(
        area,
        preparation,
        active_context,
        target_plan,
        commit_context,
        runtime,
    )


def build_diameter_target(
    area,
    ticks,
    preparation,
    active_context,
    runtime,
    sensitivity,
):
    target_plan = wheel_diameter_target_context(
        preparation.area_name,
        active_context['center_x'],
        active_context['center_y'],
        active_context['axis_angle'],
        active_context['signed_radius'],
        active_context['max_radius'],
        active_context['outer_control_radius'],
        ticks,
        sensitivity,
        axis_locked=bool(active_context['axis_lock_source']),
    )
    if target_plan['debug_message'] and runtime.debug_slow:
        runtime.debug_slow(target_plan['debug_message'])

    commit_context = wheel_diameter_target_commit_context(
        target_plan,
        active_context['axis_angle'],
        active_context['signed_radius'],
        time.time(),
    )
    target_commit = _commit_target(
        area,
        preparation,
        active_context,
        target_plan,
        commit_context,
        runtime,
    )
    target_step = {
        'done': target_commit['done'],
        'target_plan': target_plan,
        'target_signed_radius': target_plan['target_signed_radius'],
        'center_crossing': target_plan['center_crossing'],
        'target_x': target_plan['target_x'],
        'target_y': target_plan['target_y'],
        'target_outer_x': target_plan['target_outer_x'],
        'target_outer_y': target_plan['target_outer_y'],
        'target_control_angle': target_plan['target_control_angle'],
    }
    if target_step['done']:
        return {'done': True, 'target_step': target_step}

    mouse_context = build_diameter_mouse_plan(
        active_context['drag'],
        active_context['center_x'],
        active_context['center_y'],
        active_context['axis_angle'],
        active_context['signed_radius'],
        target_step['target_signed_radius'],
        target_step['target_x'],
        target_step['target_y'],
        active_context['max_radius'],
        target_step['center_crossing'],
        active_context['start_reference_x'],
        active_context['start_reference_y'],
    )
    return {
        'done': False,
        'target_step': target_step,
        'mouse_context': mouse_context,
        'target_signed_radius': target_step['target_signed_radius'],
        'center_crossing': target_step['center_crossing'],
        'target_x': target_step['target_x'],
        'target_y': target_step['target_y'],
        'target_outer_x': target_step['target_outer_x'],
        'target_outer_y': target_step['target_outer_y'],
        'target_control_angle': target_step['target_control_angle'],
        'mouse_plan': mouse_context['mouse_plan'],
        'cursor_start_x': mouse_context['cursor_start_x'],
        'cursor_start_y': mouse_context['cursor_start_y'],
        'logical_start_x': mouse_context['logical_start_x'],
        'logical_start_y': mouse_context['logical_start_y'],
        'outer_control_crossing': mouse_context['outer_control_crossing'],
    }


__all__ = ['build_diameter_target']
