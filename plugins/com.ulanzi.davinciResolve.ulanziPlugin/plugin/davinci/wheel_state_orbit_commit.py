"""Orbit and legacy segment wheel state commit helpers."""

import time

from .wheel_state_orbit_payloads import (
    wheel_orbit_feedback_payload,
    wheel_orbit_motion_payload,
    wheel_orbit_session_payload,
    wheel_segment_state_payload,
)


def commit_wheel_segment_state(manager, target_key, radius, *, updated_at=None):
    updated_at = time.time() if updated_at is None else updated_at
    manager._wheel_segment_state = wheel_segment_state_payload(
        target_key,
        radius,
        updated_at=updated_at,
    )
    return manager._wheel_segment_state


def start_wheel_orbit_session(
    manager,
    target_key,
    area_name,
    area,
    center_x,
    center_y,
    locked_radius,
    actual_radius,
    wheel_radius_value,
    start_angle,
    start_x,
    start_y,
    start_mouse_x,
    start_mouse_y,
    segment_count,
    *,
    updated_at=None,
):
    updated_at = time.time() if updated_at is None else updated_at
    manager._wheel_orbit = wheel_orbit_session_payload(
        target_key,
        area_name,
        area,
        center_x,
        center_y,
        locked_radius,
        actual_radius,
        wheel_radius_value,
        start_angle,
        start_x,
        start_y,
        start_mouse_x,
        start_mouse_y,
        segment_count,
        updated_at=updated_at,
    )
    return manager._wheel_orbit


def update_wheel_orbit_motion(manager, moving, *, updated_at=None):
    orbit = manager._wheel_orbit
    if not orbit:
        return None
    orbit.update(wheel_orbit_motion_payload(moving, updated_at=updated_at))
    return orbit


def commit_wheel_orbit_feedback_state(
    manager,
    state_angle,
    state_handle_x,
    state_handle_y,
    cursor_end_x,
    cursor_end_y,
    state_actual_radius,
    segment_count,
    *,
    updated_at=None,
):
    orbit = manager._wheel_orbit
    if not orbit:
        return None
    updated_at = time.time() if updated_at is None else updated_at
    orbit.update(wheel_orbit_feedback_payload(
        state_angle,
        state_handle_x,
        state_handle_y,
        cursor_end_x,
        cursor_end_y,
        state_actual_radius,
        segment_count,
        updated_at=updated_at,
    ))
    return orbit


__all__ = [
    'commit_wheel_orbit_feedback_state',
    'commit_wheel_segment_state',
    'start_wheel_orbit_session',
    'update_wheel_orbit_motion',
]
