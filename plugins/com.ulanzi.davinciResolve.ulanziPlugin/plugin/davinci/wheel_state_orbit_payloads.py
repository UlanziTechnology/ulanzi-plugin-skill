"""Payload builders for orbit and legacy segment state."""


def wheel_orbit_session_payload(
    target_key,
    area_name,
    area,
    center_x,
    center_y,
    locked_radius,
    actual_radius,
    wheel_radius,
    start_angle,
    handle_x,
    handle_y,
    cursor_x,
    cursor_y,
    segment_count,
    *,
    dragging=True,
    moving=True,
    updated_at=None,
):
    payload = {
        'target_key': target_key,
        'name': area_name,
        'area': area,
        'center_x': center_x,
        'center_y': center_y,
        'radius': locked_radius,
        'actual_radius': actual_radius,
        'wheel_radius': wheel_radius,
        'angle': start_angle,
        'handle_x': handle_x,
        'handle_y': handle_y,
        'x': cursor_x,
        'y': cursor_y,
        'dragging': dragging,
        'moving': moving,
        'segment_count': segment_count,
    }
    if updated_at is not None:
        payload['last_at'] = updated_at
    return payload


def wheel_orbit_motion_payload(moving, *, updated_at=None):
    payload = {'moving': moving}
    if updated_at is not None:
        payload['last_at'] = updated_at
    return payload


def wheel_orbit_release_payload(*, updated_at=None):
    payload = {
        'dragging': False,
        'moving': False,
    }
    if updated_at is not None:
        payload['last_at'] = updated_at
    return payload


def wheel_orbit_feedback_payload(
    angle,
    handle_x,
    handle_y,
    cursor_x,
    cursor_y,
    actual_radius,
    segment_count,
    *,
    updated_at=None,
):
    payload = {
        'angle': angle,
        'handle_x': handle_x,
        'handle_y': handle_y,
        'x': cursor_x,
        'y': cursor_y,
        'actual_radius': actual_radius,
        'segment_count': segment_count,
    }
    if updated_at is not None:
        payload['last_at'] = updated_at
    return payload


def wheel_segment_state_payload(target_key, radius, *, updated_at=None):
    payload = {
        'target_key': target_key,
        'radius': radius,
    }
    if updated_at is not None:
        payload['updated_at'] = updated_at
    return payload


__all__ = [
    'wheel_orbit_feedback_payload',
    'wheel_orbit_motion_payload',
    'wheel_orbit_release_payload',
    'wheel_orbit_session_payload',
    'wheel_segment_state_payload',
]
