"""Payload builders for outer-anchor wheel state."""

_MISSING = object()


def _put_if_present(payload, key, value):
    if value is not _MISSING:
        payload[key] = value


def wheel_anchor_state_payload(
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
    angle,
    handle_radius,
    actual_radius,
    handle_x,
    handle_y,
    effective_max_radius,
    *,
    source=_MISSING,
    adaptive_degrees_per_tick=_MISSING,
    adaptive_handle_radius=_MISSING,
    force_fresh_handle=_MISSING,
    visual_center_x=_MISSING,
    visual_center_y=_MISSING,
    no_progress_count=0,
    updated_at=None,
):
    payload = {
        'target_key': target_key,
        'name': area_name,
        'area': area,
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
        'visual_radius': visual_radius,
        'outer_control_radius': outer_control_radius,
        'outer_control_x': outer_control_x,
        'outer_control_y': outer_control_y,
        'angle': angle,
        'handle_radius': handle_radius,
        'actual_radius': actual_radius,
        'handle_x': handle_x,
        'handle_y': handle_y,
        'effective_max_radius': effective_max_radius,
        'no_progress_count': no_progress_count,
    }
    _put_if_present(payload, 'visual_center_x', visual_center_x)
    _put_if_present(payload, 'visual_center_y', visual_center_y)
    _put_if_present(payload, 'source', source)
    _put_if_present(payload, 'adaptive_degrees_per_tick', adaptive_degrees_per_tick)
    _put_if_present(payload, 'adaptive_handle_radius', adaptive_handle_radius)
    _put_if_present(payload, 'force_fresh_handle', force_fresh_handle)
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


__all__ = ['wheel_anchor_state_payload']
