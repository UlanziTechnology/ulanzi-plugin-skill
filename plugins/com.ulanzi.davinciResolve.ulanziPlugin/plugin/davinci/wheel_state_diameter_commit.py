"""Diameter push/pull state commit helpers."""

import time

from .config import WHEEL_ROTATION_MIN_RADIUS
from .wheel_state_accessors import mark_recent_wheel_area, wheel_state_for_area
from .wheel_state_handle_payloads import (
    wheel_handle_metadata_payload,
    wheel_handle_payload,
)
from .wheel_state_diameter_payloads import (
    wheel_diameter_state_payload,
)
from .wheel_state_anchor_payloads import wheel_anchor_state_payload
from .wheel_state_store_bridge import commit_wheel_capability_to_store


def _visual_center_from_source(source):
    if not isinstance(source, dict):
        return None, None
    visual_center_x = source.get('visual_center_x')
    visual_center_y = source.get('visual_center_y')
    if visual_center_x is None or visual_center_y is None:
        return None, None
    return visual_center_x, visual_center_y


def _resolve_visual_center(manager, area, area_name, center_x, center_y, wheel_radius, preferred=None):
    for source in (
        preferred,
        wheel_state_for_area(manager, area, center_x, center_y, wheel_radius),
        manager.handles.get(area_name, {}),
    ):
        visual_center_x, visual_center_y = _visual_center_from_source(source)
        if visual_center_x is not None and visual_center_y is not None:
            return visual_center_x, visual_center_y
    return None, None


def _sync_anchor_from_diameter_state(
    manager,
    area,
    area_name,
    target_key,
    center_x,
    center_y,
    wheel_radius,
    visual_radius,
    outer_control_radius,
    outer_control_x,
    outer_control_y,
    control_angle,
    handle_x,
    handle_y,
    signed_radius,
    effective_max_radius,
    *,
    visual_center_x=None,
    visual_center_y=None,
    source=None,
    updated_at=None,
):
    try:
        handle_radius = abs(float(signed_radius or 0.0))
    except (TypeError, ValueError):
        handle_radius = 0.0
    force_fresh_anchor = handle_radius < WHEEL_ROTATION_MIN_RADIUS
    manager._wheel_anchor_state = wheel_anchor_state_payload(
        target_key,
        area_name,
        area,
        center_x,
        center_y,
        wheel_radius,
        visual_radius,
        outer_control_radius,
        outer_control_x,
        outer_control_y,
        control_angle,
        handle_radius,
        handle_radius,
        handle_x,
        handle_y,
        effective_max_radius,
        source=source or 'diameter',
        force_fresh_handle=force_fresh_anchor,
        visual_center_x=visual_center_x,
        visual_center_y=visual_center_y,
        updated_at=updated_at,
    )


def commit_wheel_diameter_state(
    manager,
    area,
    area_name,
    target_key,
    center_x,
    center_y,
    wheel_radius,
    visual_radius,
    axis_angle,
    signed_radius,
    max_radius,
    effective_max_radius,
    outer_control_radius,
    outer_control_x,
    outer_control_y,
    control_angle,
    handle_x,
    handle_y,
    handle_angle,
    *,
    state_source=None,
    handle_source=None,
    store_source=None,
    last_detected_handle=None,
    needs_fresh_handle=None,
    commit_handle=True,
    update_stale_handle_metadata=False,
    handle_visual_radius=None,
    mark_recent=False,
    updated_at=None,
):
    updated_at = time.time() if updated_at is None else updated_at
    state_kwargs = {}
    if state_source is not None:
        state_kwargs['source'] = state_source
    if needs_fresh_handle is not None:
        state_kwargs['needs_fresh_handle'] = needs_fresh_handle
    visual_center_x, visual_center_y = _resolve_visual_center(
        manager,
        area,
        area_name,
        center_x,
        center_y,
        wheel_radius,
        preferred=last_detected_handle,
    )
    visual_center_kwargs = {}
    if visual_center_x is not None and visual_center_y is not None:
        visual_center_kwargs.update({
            'visual_center_x': visual_center_x,
            'visual_center_y': visual_center_y,
        })
    manager._wheel_diameter_state = wheel_diameter_state_payload(
        target_key,
        center_x,
        center_y,
        wheel_radius,
        visual_radius,
        axis_angle,
        signed_radius,
        max_radius,
        effective_max_radius,
        outer_control_radius,
        outer_control_x,
        outer_control_y,
        control_angle,
        updated_at=updated_at,
        **visual_center_kwargs,
        **state_kwargs,
    )

    if commit_handle:
        handle_kwargs = {}
        if handle_visual_radius is not None:
            handle_kwargs['visual_radius'] = handle_visual_radius
        if handle_source is not None:
            handle_kwargs['source'] = handle_source
        handle_kwargs.update(visual_center_kwargs)
        manager.handles[area_name] = wheel_handle_payload(
            center_x,
            center_y,
            wheel_radius,
            handle_x,
            handle_y,
            handle_angle,
            axis_angle,
            signed_radius,
            effective_max_radius=effective_max_radius,
            outer_control_radius=outer_control_radius,
            outer_control_x=outer_control_x,
            outer_control_y=outer_control_y,
            control_angle=control_angle,
            updated_at=updated_at,
            **handle_kwargs,
        )
    elif update_stale_handle_metadata:
        stale_handle = manager.handles.get(area_name)
        if stale_handle:
            stale_handle.update(wheel_handle_metadata_payload(
                center_x,
                center_y,
                wheel_radius,
                visual_radius,
                effective_max_radius,
                outer_control_radius,
                outer_control_x,
                outer_control_y,
                control_angle,
                visual_center_x=visual_center_x,
                visual_center_y=visual_center_y,
            ))

    commit_wheel_capability_to_store(
        manager,
        area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
        visual_radius=visual_radius,
        visual_center_x=visual_center_x,
        visual_center_y=visual_center_y,
        effective_max_radius=effective_max_radius,
        outer_control_radius=outer_control_radius,
        last_detected_handle=last_detected_handle,
        source=store_source,
    )
    if needs_fresh_handle:
        manager._wheel_anchor_state = None
    else:
        _sync_anchor_from_diameter_state(
            manager,
            area,
            area_name,
            target_key,
            center_x,
            center_y,
            wheel_radius,
            visual_radius,
            outer_control_radius,
            outer_control_x,
            outer_control_y,
            control_angle,
            handle_x,
            handle_y,
            signed_radius,
            effective_max_radius,
            visual_center_x=visual_center_x,
            visual_center_y=visual_center_y,
            source=state_source,
            updated_at=updated_at,
        )
    if mark_recent:
        mark_recent_wheel_area(manager, area, updated_at=updated_at)
    return manager._wheel_diameter_state


__all__ = ['commit_wheel_diameter_state']
