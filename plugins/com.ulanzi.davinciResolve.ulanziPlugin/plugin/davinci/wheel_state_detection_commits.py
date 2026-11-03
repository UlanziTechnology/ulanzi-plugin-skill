"""Detection-driven wheel handle commits."""

import math
import time

from .config import WHEEL_DIAMETER_CENTER_RESET_RADIUS
from .wheel_diameter_geometry import (
    wheel_diameter_axis_from_small_vector,
    wheel_diameter_display_angle,
)
from .wheel_state_accessors import clear_wheel_anchor_state, clear_wheel_diameter_state
from .wheel_state_axis_lock import set_wheel_diameter_axis_lock
from .wheel_state_anchor_commit import seed_wheel_anchor_state_from_overlay
from .wheel_state_handle_payloads import (
    wheel_center_reset_handle_payload,
    wheel_detected_handle_payload,
    wheel_handle_source_payload,
)
from .wheel_state_store_bridge import commit_detected_wheel_geometry_to_store

CENTER_DISPLAY_ANGLE = -math.pi / 2


def _center_handle_from_detection(
    handle,
    center_x,
    center_y,
    source,
    updated_at,
    center_axis_angle=CENTER_DISPLAY_ANGLE,
):
    return wheel_center_reset_handle_payload(
        handle,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=handle.get('wheel_radius'),
        angle=center_axis_angle,
        source=f"{source}_center",
        updated_at=updated_at,
    )


def _commit_center_handle_from_detection(
    manager,
    area,
    area_name,
    handle,
    center_x,
    center_y,
    source,
    updated_at,
    center_axis_angle=CENTER_DISPLAY_ANGLE,
):
    centered_handle = _center_handle_from_detection(
        handle,
        center_x,
        center_y,
        source,
        updated_at,
        center_axis_angle,
    )
    manager.handles[area_name] = centered_handle
    clear_wheel_anchor_state(manager)
    clear_wheel_diameter_state(manager)
    commit_detected_wheel_geometry_to_store(
        manager,
        area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=centered_handle.get('wheel_radius'),
        visual_radius=centered_handle.get('visual_radius'),
        visual_center_x=centered_handle.get('visual_center_x'),
        visual_center_y=centered_handle.get('visual_center_y'),
        last_detected_handle=centered_handle,
        source=source,
    )
    set_wheel_diameter_axis_lock(
        manager,
        area,
        center_x,
        center_y,
        center_axis_angle,
        0.0,
        source=source,
        allow_center=True,
    )
    return centered_handle


def store_wheel_handle_from_detection(manager, area, handle, source='manual_release'):
    if not area or not handle:
        return False

    area_name = area.get('name')
    if not area_name:
        return False

    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    dx = float(handle['x']) - float(center_x)
    dy = float(handle['y']) - float(center_y)
    radius = math.hypot(dx, dy)
    updated_at = time.time()
    if radius <= WHEEL_DIAMETER_CENTER_RESET_RADIUS:
        _commit_center_handle_from_detection(
            manager,
            area,
            area_name,
            handle,
            center_x,
            center_y,
            source,
            updated_at,
        )
        return True

    diameter_axis = wheel_diameter_axis_from_small_vector(dx, dy, radius)
    if diameter_axis:
        axis_angle, signed_radius = diameter_axis
        control_angle = wheel_diameter_display_angle(axis_angle, signed_radius)
    else:
        axis_angle = handle.get('radial_axis_angle', handle.get('angle', -math.pi / 2))
        signed_radius = handle.get('signed_radius', radius)
        control_angle = wheel_diameter_display_angle(axis_angle, signed_radius)

    detected_handle = wheel_detected_handle_payload(
        handle,
        center_x,
        center_y,
        axis_angle,
        signed_radius,
        control_angle,
        source,
        updated_at=updated_at,
    )
    manager.handles[area_name] = detected_handle
    commit_detected_wheel_geometry_to_store(
        manager,
        area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=detected_handle.get('wheel_radius'),
        visual_radius=detected_handle.get('visual_radius'),
        visual_center_x=detected_handle.get('visual_center_x'),
        visual_center_y=detected_handle.get('visual_center_y'),
        last_detected_handle=detected_handle,
        source=source,
    )
    seed_wheel_anchor_state_from_overlay(
        manager,
        area,
        state=detected_handle,
        source=source,
    )
    set_wheel_diameter_axis_lock(
        manager,
        area,
        center_x,
        center_y,
        axis_angle,
        signed_radius,
        source=source,
        allow_center=bool(diameter_axis),
    )
    return True


def store_hover_wheel_handle_from_detection(
    manager,
    area,
    handle,
    source='hover_detect',
    updated_at=None,
    debug_slow_fn=None,
    center_axis_angle=None,
    exact_axis_angle=None,
    exact_signed_radius=None,
):
    if not area or not handle:
        return False

    area_name = area.get('name')
    if not area_name:
        return False

    updated_at = time.time() if updated_at is None else updated_at
    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    dx = float(handle['x']) - float(center_x)
    dy = float(handle['y']) - float(center_y)
    radius = math.hypot(dx, dy)

    # Detector results intentionally use a few pixels of centre fuzz because
    # anti-aliased pixels cannot resolve a stable direction there.  The smooth
    # runtime already owns an exact geometric model, so preserve its signed
    # 1--5 px states and only call it centred at mathematical zero.
    exact_model_state = False
    try:
        parsed_exact_axis = float(exact_axis_angle)
        parsed_exact_radius = float(exact_signed_radius)
        exact_model_state = bool(
            math.isfinite(parsed_exact_axis)
            and math.isfinite(parsed_exact_radius)
        )
    except (TypeError, ValueError):
        parsed_exact_axis = None
        parsed_exact_radius = None

    is_center = (
        abs(parsed_exact_radius) <= 1e-9
        if exact_model_state
        else radius <= WHEEL_DIAMETER_CENTER_RESET_RADIUS
    )
    if is_center:
        if exact_model_state:
            center_axis_angle = parsed_exact_axis
        try:
            parsed_center_axis = float(center_axis_angle)
        except (TypeError, ValueError):
            parsed_center_axis = CENTER_DISPLAY_ANGLE
        if not math.isfinite(parsed_center_axis):
            parsed_center_axis = CENTER_DISPLAY_ANGLE
        stored_handle = _commit_center_handle_from_detection(
            manager,
            area,
            area_name,
            handle,
            center_x,
            center_y,
            source,
            updated_at,
            center_axis_angle=parsed_center_axis,
        )
        if debug_slow_fn:
            debug_slow_fn(
                f"hover wheel handle {area_name} "
                f"pos=({stored_handle['x']:.0f},{stored_handle['y']:.0f}) "
                f"radius={radius:.1f} center=1"
            )
        return True

    diameter_axis = (
        (parsed_exact_axis, parsed_exact_radius)
        if exact_model_state
        else wheel_diameter_axis_from_small_vector(dx, dy, radius)
    )
    if diameter_axis:
        axis_angle, signed_radius = diameter_axis
        control_angle = wheel_diameter_display_angle(axis_angle, signed_radius)
        stored_handle = wheel_detected_handle_payload(
            handle,
            center_x,
            center_y,
            axis_angle,
            signed_radius,
            control_angle,
            handle.get('source') or source,
            updated_at=updated_at,
        )
        set_wheel_diameter_axis_lock(
            manager,
            area,
            center_x,
            center_y,
            axis_angle,
            signed_radius,
            source=source,
            allow_center=True,
        )
    else:
        stored_handle = wheel_handle_source_payload(
            handle,
            source,
            updated_at=updated_at,
        )

    manager.handles[area_name] = stored_handle
    commit_detected_wheel_geometry_to_store(
        manager,
        area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=stored_handle.get('wheel_radius'),
        visual_radius=stored_handle.get('visual_radius'),
        visual_center_x=stored_handle.get('visual_center_x'),
        visual_center_y=stored_handle.get('visual_center_y'),
        last_detected_handle=stored_handle,
        source=source,
    )
    if diameter_axis:
        seed_wheel_anchor_state_from_overlay(
            manager,
            area,
            state=stored_handle,
            source=source,
            debug_slow_fn=debug_slow_fn,
        )
    if debug_slow_fn:
        debug_slow_fn(
            f"hover wheel handle {area_name} "
            f"pos=({stored_handle['x']:.0f},{stored_handle['y']:.0f}) "
            f"radius={radius:.1f}"
        )
    return True


__all__ = [
    'store_hover_wheel_handle_from_detection',
    'store_wheel_handle_from_detection',
]
