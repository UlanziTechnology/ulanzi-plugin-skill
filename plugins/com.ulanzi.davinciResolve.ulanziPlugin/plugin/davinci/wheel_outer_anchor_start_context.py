"""Start-handle selection for outer-anchor wheel rotation gestures."""

import math
import time

from .config import (
    WHEEL_ANCHOR_FRESH_DETECT_OUTWARD_JUMP_PX,
    WHEEL_ANCHOR_FRESH_DETECT_OUTWARD_REFERENCE_MAX_RADIUS,
    WHEEL_ANCHOR_IDLE_REDETECT_SECONDS,
    WHEEL_DIAMETER_STATE_SECONDS,
)
from .wheel_anchor_reuse_policy import wheel_anchor_is_reusable
from .wheel_fallback_handle import make_center_fallback_handle
from .wheel_outer_anchor_logic import (
    outer_anchor_detected_handle_context,
    outer_anchor_reuse_state_context,
)


def _radius_from_anchor_state(state):
    if not state:
        return None
    for key in ('actual_radius', 'handle_radius'):
        try:
            value = float(state.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 2.0:
            return value
    return None


def _radius_from_handle(area, handle):
    if not handle:
        return None
    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    try:
        dx = float(handle.get('x')) - float(center_x)
        dy = float(handle.get('y')) - float(center_y)
    except (TypeError, ValueError):
        return None
    radius = math.hypot(dx, dy)
    return radius if math.isfinite(radius) else None


def _fresh_detect_outward_jump_is_suspicious(area, handle, state):
    reference_radius = _radius_from_anchor_state(state)
    detected_radius = _radius_from_handle(area, handle)
    if reference_radius is None or detected_radius is None:
        return False, reference_radius, detected_radius
    suspicious = (
        reference_radius <= WHEEL_ANCHOR_FRESH_DETECT_OUTWARD_REFERENCE_MAX_RADIUS
        and detected_radius - reference_radius >= WHEEL_ANCHOR_FRESH_DETECT_OUTWARD_JUMP_PX
    )
    return suspicious, reference_radius, detected_radius


def wheel_outer_anchor_start_context(
    area,
    area_name,
    target_key,
    previous_diameter_state,
    now,
    detect_wheel_circle_in_area_fn,
    detect_handle_fn,
    detect_handle_raw_for_area_fn,
    wheel_anchor_state_fn,
    seed_wheel_anchor_state_from_overlay_fn,
    wheel_handle_for_area_fn,
    clear_wheel_anchor_state_fn,
    overlay_state_fn=None,
    debug_slow_fn=None,
):
    force_fresh_handle = bool(
        previous_diameter_state
        and previous_diameter_state.get('target_key') == target_key
        and now - previous_diameter_state.get('updated_at', 0) <= WHEEL_DIAMETER_STATE_SECONDS
    )
    state = wheel_anchor_state_fn()
    force_fresh_anchor_state = bool(state and state.get('force_fresh_handle'))
    if force_fresh_anchor_state and debug_slow_fn:
        debug_slow_fn(f"wheel anchor forcing fresh handle {area_name} reason=stale-feedback")
    no_progress_count = 0
    reuse_state = (
        not force_fresh_handle
        and
        not force_fresh_anchor_state
        and wheel_anchor_is_reusable(state, target_key, now, area)
    )
    if not reuse_state and not force_fresh_handle and not force_fresh_anchor_state:
        seed_wheel_anchor_state_from_overlay_fn(
            area,
            source='pre-dial',
            overlay_state_fn=overlay_state_fn,
            debug_slow_fn=debug_slow_fn,
        )
        state = wheel_anchor_state_fn()
        now = time.time()
        reuse_state = wheel_anchor_is_reusable(state, target_key, now, area)

    previous = None
    previous_from_diameter = False
    if reuse_state:
        anchor_context = outer_anchor_reuse_state_context(area, state)
        source = anchor_context['source']
        no_progress_count = anchor_context['no_progress_count']
    else:
        previous = wheel_handle_for_area_fn(area_name)
        previous_has_handle = (
            previous
            and all(key in previous for key in ('x', 'y', 'wheel_center_x', 'wheel_center_y'))
        )
        previous_source = str(previous.get('source', '')) if previous else ''
        previous_from_diameter = bool(
            previous
            and (
                previous_source.startswith('diameter')
                or previous.get('effective_max_radius') is not None
            )
        )
        previous_recent = (
            previous_has_handle
            and now - previous.get('updated_at', 0) <= WHEEL_ANCHOR_IDLE_REDETECT_SECONDS
            and not force_fresh_handle
            and not force_fresh_anchor_state
            and not previous_from_diameter
        )
        handle = None
        source = 'cached' if handle else 'detected'
        rejected_force_fresh_handle = False
        if force_fresh_anchor_state:
            handle = detect_handle_raw_for_area_fn(area)
            source = 'detected-after-stale-anchor' if handle else source
            suspicious, reference_radius, detected_radius = (
                _fresh_detect_outward_jump_is_suspicious(area, handle, state)
            )
            if suspicious:
                rejected_force_fresh_handle = True
                handle = None
                source = 'stale-anchor-radius-guard'
                if debug_slow_fn:
                    debug_slow_fn(
                        f"outer-anchor fresh detect rejected {area_name}: "
                        f"reason=outward-radius-jump "
                        f"reference_radius={reference_radius:.1f} "
                        f"detected_radius={detected_radius:.1f} "
                        f"limit={WHEEL_ANCHOR_FRESH_DETECT_OUTWARD_JUMP_PX:.1f}"
                    )
        if rejected_force_fresh_handle and state:
            anchor_context = outer_anchor_reuse_state_context(area, state)
            source = 'stale-anchor-radius-guard'
            no_progress_count = 0
        if not rejected_force_fresh_handle and not handle and (force_fresh_handle or previous_from_diameter):
            handle = detect_handle_raw_for_area_fn(area)
            source = 'detected-after-diameter' if handle else source
        if not rejected_force_fresh_handle and not handle and previous_recent:
            handle = dict(previous)
            source = 'cached'
        if not rejected_force_fresh_handle and not handle:
            handle = detect_handle_raw_for_area_fn(area)
        if (
            not rejected_force_fresh_handle
            and not handle
            and previous_has_handle
            and not force_fresh_handle
            and not force_fresh_anchor_state
            and not previous_from_diameter
        ):
            handle = dict(previous)
            source = 'cached-stale'
        if not rejected_force_fresh_handle and not handle:
            handle = detect_handle_fn(area_name)
            source = 'detect-handle'
        if not rejected_force_fresh_handle and not handle:
            wheel_geometry = detect_wheel_circle_in_area_fn(area)
            handle = make_center_fallback_handle(
                area,
                wheel_geometry,
                source='anchor_center_fallback',
            )
            source = 'center-fallback' if handle else source
        if not rejected_force_fresh_handle and not handle:
            print(f"鏈壘鍒?{area_name} 鐨勮皟鑺傜偣")
            clear_wheel_anchor_state_fn()
            return None

        if not rejected_force_fresh_handle and (
            'wheel_center_x' not in handle
            or 'wheel_center_y' not in handle
            or 'wheel_radius' not in handle
        ):
            wheel_geometry = detect_wheel_circle_in_area_fn(area)
            if wheel_geometry:
                handle.update(wheel_geometry)

        if not rejected_force_fresh_handle:
            anchor_context = outer_anchor_detected_handle_context(area, handle, previous)
            center_recovery_radius = anchor_context.get('center_recovery_radius')
            if debug_slow_fn and center_recovery_radius is not None:
                debug_slow_fn(
                    f"outer-anchor center recovery {area_name}: "
                    f"source={source} radius={center_recovery_radius:.1f}"
                )

    return {
        'state': state,
        'reuse_state': reuse_state,
        'previous': previous,
        'previous_from_diameter': previous_from_diameter,
        'force_fresh_handle': force_fresh_handle or force_fresh_anchor_state,
        'no_progress_count': no_progress_count,
        'center_x': anchor_context['center_x'],
        'center_y': anchor_context['center_y'],
        'visual_center_x': anchor_context.get('visual_center_x'),
        'visual_center_y': anchor_context.get('visual_center_y'),
        'wheel_radius': anchor_context['wheel_radius'],
        'visual_radius': anchor_context['visual_radius'],
        'handle_radius': anchor_context['handle_radius'],
        'start_angle': anchor_context['start_angle'],
        'start_x': anchor_context['start_x'],
        'start_y': anchor_context['start_y'],
        'actual_radius': anchor_context['actual_radius'],
        'center_recovery_radius': anchor_context.get('center_recovery_radius'),
        'source': source,
    }


__all__ = ['wheel_outer_anchor_start_context']
