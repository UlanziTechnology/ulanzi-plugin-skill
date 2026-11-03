"""Bridge helpers for writing shared WheelStateStore state."""

from .area_target_helpers import area_key


def _update_wheel_state(
    manager,
    area,
    center_x=None,
    center_y=None,
    visual_center_x=None,
    visual_center_y=None,
    wheel_radius=None,
    visual_radius=None,
    effective_max_radius=None,
    outer_control_radius=None,
    last_detected_handle=None,
    source=None,
):
    if not area or area.get('type') != 'wheel':
        return None
    kwargs = {
        'area_key': area_key(area),
        'area': area,
        'center_x': center_x,
        'center_y': center_y,
        'visual_center_x': visual_center_x,
        'visual_center_y': visual_center_y,
        'wheel_radius': wheel_radius,
        'visual_radius': visual_radius,
        'source': source,
    }
    if effective_max_radius is not None:
        kwargs['effective_max_radius'] = effective_max_radius
    if outer_control_radius is not None:
        kwargs['outer_control_radius'] = outer_control_radius
    if last_detected_handle is not None:
        kwargs['last_detected_handle'] = last_detected_handle
    return manager._wheel_state_store.update(**kwargs)


def commit_detected_wheel_geometry_to_store(
    manager,
    area,
    *,
    center_x,
    center_y,
    wheel_radius,
    visual_radius,
    visual_center_x=None,
    visual_center_y=None,
    last_detected_handle=None,
    source=None,
):
    return _update_wheel_state(
        manager,
        area,
        center_x=center_x,
        center_y=center_y,
        visual_center_x=visual_center_x,
        visual_center_y=visual_center_y,
        wheel_radius=wheel_radius,
        visual_radius=visual_radius,
        last_detected_handle=last_detected_handle,
        source=source,
    )


def commit_wheel_capability_to_store(
    manager,
    area,
    *,
    center_x,
    center_y,
    wheel_radius,
    visual_radius,
    effective_max_radius,
    outer_control_radius,
    visual_center_x=None,
    visual_center_y=None,
    last_detected_handle=None,
    source=None,
):
    return _update_wheel_state(
        manager,
        area,
        center_x=center_x,
        center_y=center_y,
        visual_center_x=visual_center_x,
        visual_center_y=visual_center_y,
        wheel_radius=wheel_radius,
        visual_radius=visual_radius,
        effective_max_radius=effective_max_radius,
        outer_control_radius=outer_control_radius,
        last_detected_handle=last_detected_handle,
        source=source,
    )


def refresh_wheel_overlay_from_state_manager(manager, area, area_name=None):
    refresh_overlay = getattr(manager, '_refresh_wheel_overlay_state_fn', None)
    if not callable(refresh_overlay):
        return None
    return refresh_overlay(area, area_name)


__all__ = [
    'commit_detected_wheel_geometry_to_store',
    'commit_wheel_capability_to_store',
    'refresh_wheel_overlay_from_state_manager',
]
