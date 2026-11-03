"""Payload builders for diameter push/pull state."""

_MISSING = object()


def _put_if_present(payload, key, value):
    if value is not _MISSING:
        payload[key] = value


def wheel_diameter_axis_lock_payload(
    target_key,
    area_name,
    center_x,
    center_y,
    axis_angle,
    signed_radius,
    source,
    *,
    updated_at=None,
):
    payload = {
        'target_key': target_key,
        'name': area_name,
        'center_x': center_x,
        'center_y': center_y,
        'axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'source': source,
    }
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


def wheel_diameter_state_payload(
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
    *,
    mode='outer_ring',
    source=_MISSING,
    needs_fresh_handle=_MISSING,
    visual_center_x=_MISSING,
    visual_center_y=_MISSING,
    updated_at=None,
):
    payload = {
        'target_key': target_key,
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
        'visual_radius': visual_radius,
        'axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'max_radius': max_radius,
        'effective_max_radius': effective_max_radius,
        'mode': mode,
        'outer_control_radius': outer_control_radius,
        'outer_control_x': outer_control_x,
        'outer_control_y': outer_control_y,
        'control_angle': control_angle,
    }
    _put_if_present(payload, 'visual_center_x', visual_center_x)
    _put_if_present(payload, 'visual_center_y', visual_center_y)
    _put_if_present(payload, 'source', source)
    _put_if_present(payload, 'needs_fresh_handle', needs_fresh_handle)
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


def wheel_diameter_drag_payload(
    target_key,
    area_name,
    area,
    center_x,
    center_y,
    wheel_radius,
    max_radius,
    effective_max_radius,
    outer_control_radius,
    axis_angle,
    signed_radius,
    press_x,
    press_y,
    logical_start_x,
    logical_start_y,
    safe_press_used,
    axis_lock_source,
    predicted_handle_x,
    predicted_handle_y,
    *,
    confirmed_signed_radius=None,
    visual_center_x=_MISSING,
    visual_center_y=_MISSING,
    updated_at=None,
):
    if confirmed_signed_radius is None:
        confirmed_signed_radius = signed_radius
    payload = {
        'target_key': target_key,
        'name': area_name,
        'area': area,
        'gesture_mode': 'diameter',
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
        'max_radius': max_radius,
        'effective_max_radius': effective_max_radius,
        'outer_control_radius': outer_control_radius,
        'axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'confirmed_signed_radius': confirmed_signed_radius,
        'x': press_x,
        'y': press_y,
        'button_down': True,
        'press_x': press_x,
        'press_y': press_y,
        'logical_start_x': logical_start_x,
        'logical_start_y': logical_start_y,
        'safe_press_used': safe_press_used,
        'axis_lock_source': axis_lock_source,
        'predicted_handle_x': predicted_handle_x,
        'predicted_handle_y': predicted_handle_y,
    }
    _put_if_present(payload, 'visual_center_x', visual_center_x)
    _put_if_present(payload, 'visual_center_y', visual_center_y)
    if updated_at is not None:
        payload['last_at'] = updated_at
    return payload


def wheel_diameter_drag_update_payload(
    predicted_handle_x,
    predicted_handle_y,
    axis_angle,
    signed_radius,
    effective_max_radius,
    outer_control_radius,
    *,
    updated_at=None,
):
    payload = {
        'predicted_handle_x': predicted_handle_x,
        'predicted_handle_y': predicted_handle_y,
        'axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'effective_max_radius': effective_max_radius,
        'outer_control_radius': outer_control_radius,
    }
    if updated_at is not None:
        payload['last_at'] = updated_at
    return payload


def wheel_diameter_drag_final_payload(
    cursor_x,
    cursor_y,
    axis_angle,
    signed_radius,
    effective_max_radius,
    predicted_handle_x,
    predicted_handle_y,
    outer_control_radius,
    outer_control_x,
    outer_control_y,
    control_angle,
    *,
    updated_at=None,
):
    payload = {
        'x': cursor_x,
        'y': cursor_y,
        'axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'confirmed_signed_radius': signed_radius,
        'effective_max_radius': effective_max_radius,
        'predicted_handle_x': predicted_handle_x,
        'predicted_handle_y': predicted_handle_y,
        'outer_control_radius': outer_control_radius,
        'outer_control_x': outer_control_x,
        'outer_control_y': outer_control_y,
        'control_angle': control_angle,
    }
    if updated_at is not None:
        payload['last_at'] = updated_at
    return payload


def wheel_diameter_drag_repress_payload(
    press_x,
    press_y,
    predicted_handle_x,
    predicted_handle_y,
):
    return {
        'x': press_x,
        'y': press_y,
        'button_down': True,
        'press_x': press_x,
        'press_y': press_y,
        'predicted_handle_x': predicted_handle_x,
        'predicted_handle_y': predicted_handle_y,
    }


__all__ = [
    'wheel_diameter_axis_lock_payload',
    'wheel_diameter_drag_final_payload',
    'wheel_diameter_drag_payload',
    'wheel_diameter_drag_repress_payload',
    'wheel_diameter_drag_update_payload',
    'wheel_diameter_state_payload',
]
