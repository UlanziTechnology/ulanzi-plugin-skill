"""Payload builders for cached wheel handle state."""

import time

_MISSING = object()


def _put_if_present(payload, key, value):
    if value is not _MISSING:
        payload[key] = value


def wheel_handle_payload(
    center_x,
    center_y,
    wheel_radius,
    x,
    y,
    angle,
    radial_axis_angle,
    signed_radius,
    *,
    radius=None,
    visual_radius=_MISSING,
    effective_max_radius=_MISSING,
    outer_control_radius=_MISSING,
    outer_control_x=_MISSING,
    outer_control_y=_MISSING,
    visual_center_x=_MISSING,
    visual_center_y=_MISSING,
    control_angle=_MISSING,
    adaptive_degrees_per_tick=_MISSING,
    adaptive_handle_radius=_MISSING,
    source=_MISSING,
    updated_at=None,
):
    payload = {
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'wheel_radius': wheel_radius,
        'x': x,
        'y': y,
        'angle': angle,
        'radial_axis_angle': radial_axis_angle,
        'signed_radius': signed_radius,
        'radius': abs(signed_radius) if radius is None else radius,
    }
    _put_if_present(payload, 'visual_radius', visual_radius)
    _put_if_present(payload, 'effective_max_radius', effective_max_radius)
    _put_if_present(payload, 'outer_control_radius', outer_control_radius)
    _put_if_present(payload, 'outer_control_x', outer_control_x)
    _put_if_present(payload, 'outer_control_y', outer_control_y)
    _put_if_present(payload, 'visual_center_x', visual_center_x)
    _put_if_present(payload, 'visual_center_y', visual_center_y)
    _put_if_present(payload, 'control_angle', control_angle)
    _put_if_present(payload, 'adaptive_degrees_per_tick', adaptive_degrees_per_tick)
    _put_if_present(payload, 'adaptive_handle_radius', adaptive_handle_radius)
    _put_if_present(payload, 'source', source)
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


def wheel_detected_handle_payload(
    handle,
    center_x,
    center_y,
    axis_angle,
    signed_radius,
    control_angle,
    source,
    *,
    updated_at=None,
):
    payload = dict(handle or {})
    payload.pop('visual_invalidated', None)
    payload.update({
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'angle': control_angle,
        'radial_axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'radius': abs(signed_radius),
        'control_angle': control_angle,
        'source': source,
    })
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


def wheel_center_reset_handle_payload(
    handle=None,
    *,
    center_x,
    center_y,
    wheel_radius=_MISSING,
    angle=0.0,
    source='center_reset',
    updated_at=None,
):
    payload = dict(handle or {})
    for key in (
        'visual_invalidated',
        'control_angle',
        'outer_control_radius',
        'outer_control_x',
        'outer_control_y',
    ):
        payload.pop(key, None)
    payload.update({
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'x': center_x,
        'y': center_y,
        'angle': angle,
        'radial_axis_angle': angle,
        'control_angle': angle,
        'signed_radius': 0.0,
        'radius': 0.0,
        'source': source,
    })
    _put_if_present(payload, 'wheel_radius', wheel_radius)
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


def wheel_handle_metadata_payload(
    center_x,
    center_y,
    wheel_radius,
    visual_radius,
    effective_max_radius,
    outer_control_radius,
    outer_control_x,
    outer_control_y,
    control_angle,
    visual_center_x=_MISSING,
    visual_center_y=_MISSING,
):
    payload = {
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'wheel_radius': wheel_radius,
        'visual_radius': visual_radius,
        'effective_max_radius': effective_max_radius,
        'outer_control_radius': outer_control_radius,
        'outer_control_x': outer_control_x,
        'outer_control_y': outer_control_y,
        'control_angle': control_angle,
    }
    _put_if_present(payload, 'visual_center_x', visual_center_x)
    _put_if_present(payload, 'visual_center_y', visual_center_y)
    return payload


def wheel_handle_source_payload(handle, source, *, updated_at=None):
    payload = dict(handle or {})
    payload.pop('visual_invalidated', None)
    payload['source'] = payload.get('source') or source
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


def wheel_handle_timestamp_payload(handle, *, updated_at=None):
    payload = dict(handle or {})
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


def wheel_last_detected_handle_snapshot(handle, *, updated_at=None):
    if not isinstance(handle, dict):
        return None

    payload = {}
    for key in (
        'x',
        'y',
        'wheel_center_x',
        'wheel_center_y',
        'visual_center_x',
        'visual_center_y',
        'wheel_radius',
        'visual_radius',
        'angle',
        'radial_axis_angle',
        'signed_radius',
        'diameter_last_side',
        'last_nonzero_axis_x',
        'last_nonzero_axis_y',
        'radius',
        'source',
    ):
        if key in handle:
            payload[key] = handle.get(key)
    if updated_at is None:
        updated_at = time.time()
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


__all__ = [
    'wheel_center_reset_handle_payload',
    'wheel_detected_handle_payload',
    'wheel_last_detected_handle_snapshot',
    'wheel_handle_metadata_payload',
    'wheel_handle_payload',
    'wheel_handle_source_payload',
    'wheel_handle_timestamp_payload',
]
