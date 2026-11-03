"""Creation and reuse of wheel diameter drag sessions."""

import time

from ..area_target_helpers import area_key
from ..wheel_diameter_handle_context import (
    wheel_diameter_geometry_from_handle_context,
    wheel_diameter_initial_handle_context,
)
from ..wheel_diameter_logic import wheel_diameter_edge_lock_plan
from ..wheel_diameter_press_context import wheel_diameter_axis_press_context
from ..wheel_diameter_state_context import wheel_diameter_reuse_drag_context
from ..wheel_state_diameter_payloads import wheel_diameter_drag_payload
from .runtime import DiameterPreparation, WheelDiameterRuntime


def prepare_diameter_session(area, runtime: WheelDiameterRuntime):
    runtime.clear_wheel_orbit()
    runtime.release_param_drag()
    return DiameterPreparation(
        area_name=area['name'],
        target_key=area_key(area),
        now=time.time(),
    )


def _active_reuse_decision(target_key, runtime):
    drag = runtime.state.wheel_drag_state()
    reuse_drag = (
        drag
        and drag.get('gesture_mode') == 'diameter'
        and drag.get('target_key') == target_key
        and drag.get('button_down', True)
    )
    if drag and not reuse_drag:
        runtime.release_wheel_drag()
        drag = None
        reuse_drag = False
    return drag, reuse_drag


def _reuse_drag_start_context(area, drag, runtime):
    center_x = drag['center_x']
    center_y = drag['center_y']
    wheel_radius = drag.get('wheel_radius')
    wheel_state = runtime.state.wheel_state_for_area(
        area,
        center_x,
        center_y,
        wheel_radius,
    )
    reuse_context = wheel_diameter_reuse_drag_context(drag, area, wheel_state)
    drag.update(reuse_context['drag_updates'])
    return reuse_context


def _active_reuse_context(area, drag, runtime):
    reuse_context = _reuse_drag_start_context(area, drag, runtime)
    return {
        'ok': True,
        'done': False,
        'drag': drag,
        'handle': drag,
        'center_x': reuse_context['center_x'],
        'center_y': reuse_context['center_y'],
        'wheel_radius': reuse_context['wheel_radius'],
        'max_radius': reuse_context['max_radius'],
        'effective_max_radius': reuse_context['effective_max_radius'],
        'visual_radius': reuse_context['visual_radius'],
        'outer_control_radius': reuse_context['outer_control_radius'],
        'axis_angle': reuse_context['axis_angle'],
        'signed_radius': reuse_context['signed_radius'],
        'confirmed_signed_radius': reuse_context['confirmed_signed_radius'],
        'axis_lock_source': reuse_context['axis_lock_source'],
        'drag_source': reuse_context['drag_source'],
        'start_reference_x': reuse_context['start_reference_x'],
        'start_reference_y': reuse_context['start_reference_y'],
    }


def _initial_handle_stage(area, preparation, runtime):
    initial_context = wheel_diameter_initial_handle_context(
        area,
        preparation.area_name,
        preparation.target_key,
        preparation.now,
        runtime.detect_wheel_circle_in_area,
        runtime.detect_handle,
        runtime.detect_raw_handle,
        runtime.state.wheel_diameter_state,
        runtime.state.wheel_handle_for_area,
        runtime.state.wheel_anchor_state,
        runtime.debug_slow,
    )
    if not initial_context['handle']:
        print(f"[wheel-diameter] handle not found: {preparation.area_name}")
        runtime.state.clear_wheel_diameter_state()
        return None
    return initial_context


def _geometry_stage(area, preparation, initial_context, runtime):
    state = initial_context['state']
    previous = initial_context['previous']
    reuse_state = initial_context['reuse_state']
    state_needs_fresh_handle = initial_context['state_needs_fresh_handle']
    previous_has_handle = initial_context['previous_has_handle']
    geometry_context = wheel_diameter_geometry_from_handle_context(
        area,
        preparation.area_name,
        initial_context['handle'],
        state,
        previous,
        previous_has_handle,
        reuse_state,
        state_needs_fresh_handle,
        initial_context['used_cached_handle'],
        lambda center_x, center_y, wheel_radius: runtime.state.wheel_state_for_area(
            area,
            center_x,
            center_y,
            wheel_radius,
        ),
        runtime.detect_wheel_circle_in_area,
        runtime.debug_slow,
    )
    return {
        'state': state,
        'previous': previous,
        'reuse_state': reuse_state,
        'state_needs_fresh_handle': state_needs_fresh_handle,
        'previous_has_handle': previous_has_handle,
        'drag_source': initial_context['drag_source'],
        'handle': geometry_context['handle'],
        'center_x': geometry_context['center_x'],
        'center_y': geometry_context['center_y'],
        'wheel_radius': geometry_context['wheel_radius'],
        'max_radius': geometry_context['max_radius'],
        'effective_max_radius': geometry_context['effective_max_radius'],
        'visual_radius': geometry_context['visual_radius'],
        'outer_control_radius': geometry_context['outer_control_radius'],
        'used_cached_handle': geometry_context['used_cached_handle'],
    }


def _commit_edge_lock_if_needed(
    area,
    ticks,
    preparation,
    geometry,
    runtime,
    sensitivity,
):
    edge_lock = wheel_diameter_edge_lock_plan(
        geometry['reuse_state'],
        geometry['state_needs_fresh_handle'],
        geometry['state'],
        ticks,
        sensitivity,
        geometry['max_radius'],
        geometry['effective_max_radius'],
        geometry['outer_control_radius'],
        geometry['center_x'],
        geometry['center_y'],
    )
    if not edge_lock['locked']:
        return False
    runtime.state.commit_wheel_diameter_state(
        area,
        preparation.area_name,
        preparation.target_key,
        geometry['center_x'],
        geometry['center_y'],
        geometry['wheel_radius'],
        geometry['visual_radius'],
        edge_lock['axis_angle'],
        edge_lock['locked_signed_radius'],
        edge_lock['edge_radius'],
        geometry['effective_max_radius'],
        geometry['outer_control_radius'],
        edge_lock['outer_x'],
        edge_lock['outer_y'],
        edge_lock['outer_angle'],
        edge_lock['locked_x'],
        edge_lock['locked_y'],
        edge_lock['state_angle'],
        state_source='diameter_edge_lock',
        store_source='diameter_edge_lock',
        mark_recent=True,
    )
    return True


def _begin_pressed_drag(
    area,
    ticks,
    preparation,
    geometry,
    runtime,
    sensitivity,
):
    press = wheel_diameter_axis_press_context(
        area,
        preparation.area_name,
        geometry['handle'],
        geometry['center_x'],
        geometry['center_y'],
        geometry['max_radius'],
        geometry['reuse_state'],
        geometry['state'],
        geometry['state_needs_fresh_handle'],
        geometry['used_cached_handle'],
        ticks,
        lambda center_x, center_y: runtime.state.wheel_diameter_axis_lock_for_area(
            area,
            center_x,
            center_y,
        ),
        sensitivity,
        runtime.debug_slow,
    )
    if not runtime.mouse_drag_begin(press['press_x'], press['press_y']):
        return {'ok': False, 'done': False}

    handle = press['handle']
    drag = wheel_diameter_drag_payload(
        preparation.target_key,
        preparation.area_name,
        area,
        geometry['center_x'],
        geometry['center_y'],
        geometry['wheel_radius'],
        geometry['max_radius'],
        geometry['effective_max_radius'],
        geometry['outer_control_radius'],
        press['axis_angle'],
        press['signed_radius'],
        press['press_x'],
        press['press_y'],
        press['start_reference_x'],
        press['start_reference_y'],
        press['safe_press_used'],
        press['axis_lock_source'],
        handle['x'],
        handle['y'],
        confirmed_signed_radius=press['confirmed_signed_radius'],
        visual_center_x=handle.get('visual_center_x'),
        visual_center_y=handle.get('visual_center_y'),
        updated_at=preparation.now,
    )
    runtime.state.set_wheel_drag_state(drag)
    return {
        'ok': True,
        'done': False,
        'drag': drag,
        'handle': handle,
        'center_x': geometry['center_x'],
        'center_y': geometry['center_y'],
        'wheel_radius': geometry['wheel_radius'],
        'max_radius': geometry['max_radius'],
        'effective_max_radius': geometry['effective_max_radius'],
        'visual_radius': geometry['visual_radius'],
        'outer_control_radius': geometry['outer_control_radius'],
        'axis_angle': press['axis_angle'],
        'signed_radius': press['signed_radius'],
        'confirmed_signed_radius': press['confirmed_signed_radius'],
        'axis_lock_source': press['axis_lock_source'],
        'drag_source': geometry['drag_source'],
        'start_reference_x': press['start_reference_x'],
        'start_reference_y': press['start_reference_y'],
    }


def _begin_diameter_drag(area, ticks, preparation, runtime, sensitivity):
    initial_context = _initial_handle_stage(area, preparation, runtime)
    if initial_context is None:
        return {'ok': False, 'done': False}

    geometry = _geometry_stage(area, preparation, initial_context, runtime)
    if _commit_edge_lock_if_needed(
        area,
        ticks,
        preparation,
        geometry,
        runtime,
        sensitivity,
    ):
        return {'ok': True, 'done': True}

    return _begin_pressed_drag(
        area,
        ticks,
        preparation,
        geometry,
        runtime,
        sensitivity,
    )


def begin_or_reuse_diameter_drag(
    area,
    ticks,
    preparation,
    runtime,
    sensitivity,
):
    drag, reuse_drag = _active_reuse_decision(preparation.target_key, runtime)
    if reuse_drag:
        return _active_reuse_context(area, drag, runtime)
    return _begin_diameter_drag(
        area,
        ticks,
        preparation,
        runtime,
        sensitivity,
    )


__all__ = [
    'begin_or_reuse_diameter_drag',
    'prepare_diameter_session',
]
