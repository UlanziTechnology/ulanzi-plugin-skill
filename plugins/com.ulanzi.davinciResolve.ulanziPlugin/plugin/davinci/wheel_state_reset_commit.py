"""Wheel reset handle commit helpers."""

import math
import time

from .wheel_state_accessors import clear_wheel_anchor_state, clear_wheel_diameter_state
from .wheel_state_axis_lock import set_wheel_diameter_axis_lock
from .wheel_state_handle_payloads import wheel_center_reset_handle_payload
from .wheel_state_store_bridge import (
    commit_detected_wheel_geometry_to_store,
    refresh_wheel_overlay_from_state_manager,
)


def commit_wheel_center_reset_state(
    manager,
    area,
    handle=None,
    *,
    center_x,
    center_y,
    wheel_radius=None,
    angle=0.0,
    updated_at=None,
    refresh_overlay=True,
):
    if not area or area.get('type') != 'wheel':
        return None

    area_name = area.get('name')
    if not area_name:
        return None

    updated_at = time.time() if updated_at is None else updated_at
    payload_kwargs = {
        'center_x': center_x,
        'center_y': center_y,
        'angle': angle,
        'updated_at': updated_at,
    }
    if wheel_radius is not None:
        payload_kwargs['wheel_radius'] = wheel_radius
    reset_handle = wheel_center_reset_handle_payload(handle, **payload_kwargs)
    reset_handle.update({
        'diameter_last_side': 0,
        'last_nonzero_axis_x': math.cos(angle),
        'last_nonzero_axis_y': math.sin(angle),
    })
    backend = getattr(manager, '_smooth_wheel_backend', None)
    trace = getattr(backend, 'record_diagnostic', None)
    if callable(trace):
        try:
            trace('reset_commit', area=dict(area),
                  observedHandle=dict(handle) if isinstance(handle, dict) else None,
                  resetHandle=dict(reset_handle),
                  observedHandleAvailable=isinstance(handle, dict))
        except Exception:
            pass
    manager.handles[area_name] = reset_handle
    clear_wheel_diameter_state(manager)
    clear_wheel_anchor_state(manager)
    commit_detected_wheel_geometry_to_store(
        manager,
        area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=reset_handle.get('wheel_radius'),
        visual_radius=reset_handle.get('visual_radius'),
        visual_center_x=reset_handle.get('visual_center_x'),
        visual_center_y=reset_handle.get('visual_center_y'),
        last_detected_handle=reset_handle,
        source=reset_handle.get('source'),
    )
    set_wheel_diameter_axis_lock(
        manager,
        area,
        center_x,
        center_y,
        angle,
        0.0,
        source=reset_handle.get('source'),
        allow_center=True,
    )
    if refresh_overlay:
        refresh_wheel_overlay_from_state_manager(manager, area, area_name)
    return reset_handle


__all__ = ['commit_wheel_center_reset_state']
