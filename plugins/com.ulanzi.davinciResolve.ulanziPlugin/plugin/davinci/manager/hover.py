"""Consolidated DaVinci manager hover responsibilities."""

import math
import time

from ..area_target_helpers import area_at_point, area_contains_point, area_key, area_label
from ..layout_cache import layout_geometry_key
from ..layout_scan_guard import (
    LayoutScanSuperseded, check_layout_scan, make_layout_scan_checkpoint,
    smooth_layout_busy,
)
from ..wheel_overlay_controller import show_hover_overlay
from ..wheel_overlay_state_context import refresh_existing_hover_overlay
from ..wheel_overlay_visibility import (
    clear_hover_overlays,
    hide_inactive_overlays,
    set_wheel_dot_hidden,
)
from ..wheel_state_accessors import (
    active_wheel_target_area,
    clear_wheel_control_state,
    lock_wheel_target,
    recent_wheel_area,
    remove_wheel_handle,
    wheel_drag_state,
    wheel_orbit_state,
)


PENDING_SWITCH_CLICK_SECONDS = 1.5


def is_hover_locked(manager, *, time_fn=time.time):
    return time_fn() < manager._hover_lock_until or active_wheel_target_area(manager) is not None


def lock_hover_for_param_dial(manager, *, lock_seconds, time_fn=time.time):
    manager._hover_lock_until = max(
        manager._hover_lock_until,
        time_fn() + lock_seconds,
    )


def lock_hover_for_wheel_dial(manager, area=None, *, lock_seconds, time_fn=time.time):
    manager._hover_lock_until = max(
        manager._hover_lock_until,
        time_fn() + lock_seconds,
    )
    if area and area.get('type') == 'wheel':
        lock_wheel_target(manager, area)


def note_param_dial_activity(manager, *, lock_seconds, time_fn=time.time):
    manager._last_param_dial_activity_at = time_fn()
    lock_hover_for_param_dial(manager, lock_seconds=lock_seconds, time_fn=time_fn)


def note_wheel_dial_activity(
    manager,
    area=None,
    *,
    lock_seconds,
    debug_slow_fn=None,
    time_fn=time.time,
):
    manager._last_wheel_dial_activity_at = time_fn()
    active_area = active_wheel_target_area(manager)
    if active_area and area and area_key(active_area) != area_key(area):
        if debug_slow_fn:
            debug_slow_fn(
                f"wheel target lock keep {area_label(active_area)} "
                f"over {area_label(area)}"
            )
        area = active_area
    if area is None:
        area = active_area
    if area is None and manager.current_hover_area and manager.current_hover_area.get('type') == 'wheel':
        area = manager.current_hover_area
    if area is None:
        area = recent_wheel_area(manager)
    lock_hover_for_wheel_dial(manager, area, lock_seconds=lock_seconds, time_fn=time_fn)


def make_areas_signature(areas):
    return tuple(
        (
            area.get('id'),
            area.get('type'),
            round(float(area.get('x', 0))),
            round(float(area.get('y', 0))),
            round(float(area.get('w', 0))),
            round(float(area.get('h', 0))),
        )
        for area in areas
    )


def request_layout_refresh(manager, reason='requested'):
    manager._layout_refresh_requested = True
    manager._layout_refresh_reason = reason


def note_user_mouse_move(
    manager,
    mouse_x,
    mouse_y,
    *,
    plugin_mouse_button_active_fn,
    left_mouse_button_down_fn,
    min_distance_px,
):
    if plugin_mouse_button_active_fn():
        return
    if left_mouse_button_down_fn():
        return

    previous = manager._last_user_mouse_pos
    if previous is not None:
        distance = math.hypot(mouse_x - previous[0], mouse_y - previous[1])
        if distance < min_distance_px:
            return

    manager._last_user_mouse_pos = (float(mouse_x), float(mouse_y))
    manager._last_user_mouse_move_at = time.time()


def can_refresh_layout(
    manager,
    *,
    left_mouse_button_down_fn,
    plugin_mouse_button_active_fn,
    param_refresh_grace_seconds,
    wheel_refresh_grace_seconds,
):
    # Never scan during an owned drag, including queued motion after input
    # stops. Idle armed sessions may scan again after the normal quiet period.
    if smooth_layout_busy(manager):
        return False
    input_at = getattr(manager, '_last_layout_input_at', 0.0)
    if input_at and time.time() - input_at < wheel_refresh_grace_seconds:
        return False
    if manager._manual_wheel_drag:
        return False
    if left_mouse_button_down_fn() and not plugin_mouse_button_active_fn():
        return False
    if manager._param_drag or wheel_drag_state(manager) or is_hover_locked(manager):
        return False
    if (
        manager._last_param_dial_activity_at
        and time.time() - manager._last_param_dial_activity_at < param_refresh_grace_seconds
    ):
        return False
    if (
        manager._last_wheel_dial_activity_at
        and time.time() - manager._last_wheel_dial_activity_at < wheel_refresh_grace_seconds
    ):
        return False
    orbit = wheel_orbit_state(manager)
    if orbit and (orbit.get('dragging') or orbit.get('moving')):
        return False
    return True


def layout_refresh_due(
    manager,
    now,
    *,
    can_refresh_layout_fn,
    interval_seconds,
    mouse_idle_seconds,
    mouse_move_max_age_seconds,
    force_min_interval_seconds,
    idle_fallback_seconds,
):
    if not can_refresh_layout_fn():
        return False, None

    since_refresh = now - manager._last_state_update
    if manager._layout_refresh_requested:
        if since_refresh >= force_min_interval_seconds:
            return True, manager._layout_refresh_reason or 'requested'
        return False, None

    if not manager.areas and since_refresh >= force_min_interval_seconds:
        return True, 'areas-missing'

    if manager._last_user_mouse_move_at > manager._last_layout_refresh_mouse_move_at:
        mouse_idle = now - manager._last_user_mouse_move_at
        if (
            mouse_idle >= mouse_idle_seconds
            and mouse_idle <= mouse_move_max_age_seconds
            and since_refresh >= interval_seconds
        ):
            if manager.current_hover_area:
                return False, None
            if manager._last_user_mouse_pos and area_at_point(
                manager.areas,
                *manager._last_user_mouse_pos,
            ):
                return False, None
            return True, 'mouse-idle'

    if idle_fallback_seconds > 0 and since_refresh >= idle_fallback_seconds:
        return True, 'idle-fallback'

    return False, None


def clear_runtime_target_cache(manager):
    smooth_backend = getattr(manager, '_smooth_wheel_backend', None)
    token = object()
    suspend = getattr(smooth_backend, 'suspend', None)
    resume = getattr(smooth_backend, 'resume', None)
    if callable(suspend):
        suspend('layout_changed', token=token)
    elif smooth_backend is not None:
        smooth_backend.cancel('layout_changed')
    try:
        hide_inactive_overlays(manager)
        manager._pending_hover_overlay_key = None
        manager._pending_hover_overlay_at = 0.0
        manager._manual_wheel_drag = None
        manager.current_hover_area = None
        clear_wheel_control_state(
            manager,
            clear_handles_cache=True,
            clear_recent=True,
            clear_target_lock=True,
            clear_segment=True,
            clear_anchor=True,
            clear_diameter=True,
            clear_state_store=True,
        )
    finally:
        if callable(resume):
            resume('layout_changed', token=token)


def process_scheduled_layout_refresh(
    manager,
    *,
    layout_refresh_due_fn,
    update_state_fn,
    debug_slow_fn=None,
    debug_update_state_ms=0.0,
    wheel_refresh_grace_seconds=2.5,
):
    if not manager.is_monitoring:
        return False

    now = time.time()
    refresh_due, refresh_reason = layout_refresh_due_fn(now)
    if not refresh_due:
        return False

    manager._last_state_update = now
    manager._layout_refresh_requested = False
    manager._layout_refresh_reason = None
    update_started_at = time.perf_counter()
    checkpoint = make_layout_scan_checkpoint(manager, wheel_refresh_grace_seconds)
    finder = getattr(manager, 'label_finder', None)
    old_checkpoint = getattr(manager, '_layout_scan_checkpoint', None)
    old_finder_checkpoint = getattr(finder, '_layout_scan_checkpoint', None)
    old_labels = getattr(finder, 'labels', None)
    manager._layout_scan_checkpoint = checkpoint
    if finder is not None:
        finder._layout_scan_checkpoint = checkpoint
    try:
        checkpoint()
        update_state_fn()
    except LayoutScanSuperseded:
        # Keep the last complete layout and retry only once input/session gates
        # allow it. Do not publish partial labels or turn cancellation into an
        # empty-layout/recognition failure.
        if finder is not None and old_labels is not None:
            finder.labels = old_labels
        if not manager._layout_refresh_requested:
            manager._layout_refresh_requested = True
            manager._layout_refresh_reason = refresh_reason or 'input-yield'
        if debug_slow_fn:
            elapsed = (time.perf_counter() - update_started_at) * 1000.0
            debug_slow_fn(f"layout scan yielded to wheel input {elapsed:.1f}ms; cached layout retained")
        return False
    finally:
        manager._layout_scan_checkpoint = old_checkpoint
        if finder is not None:
            finder._layout_scan_checkpoint = old_finder_checkpoint
    manager._last_layout_refresh_mouse_move_at = manager._last_user_mouse_move_at
    update_ms = (time.perf_counter() - update_started_at) * 1000.0
    if debug_slow_fn and update_ms >= debug_update_state_ms:
        debug_slow_fn(
            f"scheduled state refresh {update_ms:.1f}ms "
            f"reason={refresh_reason} areas={len(manager.areas)}"
        )
    return True


def current_layout_geometry_key(manager):
    finder = getattr(manager, 'label_finder', None)
    if not finder:
        return None
    get_window_frame = getattr(finder, 'get_window_frame', None)
    if not get_window_frame:
        return None
    return layout_geometry_key(
        get_window_frame(),
        hwnd=getattr(finder, 'target_hwnd', 0),
    )


def note_layout_switch_click(
    manager,
    mouse_x,
    mouse_y,
    *,
    plugin_mouse_button_active_fn,
    sync_wheel_overlays_fn,
    check_hover_fn,
    debug_slow_fn=None,
):
    if plugin_mouse_button_active_fn():
        return False
    if area_at_point(manager.areas, mouse_x, mouse_y):
        return False

    geometry_key = current_layout_geometry_key(manager)
    if not geometry_key:
        return False

    now = time.time()
    pending = manager._layout_pending_switch_click
    if (
        pending
        and pending.get('geometry_key') == geometry_key
        and now - pending.get('at', 0.0) <= PENDING_SWITCH_CLICK_SECONDS
        and manager._layout_refresh_requested
    ):
        if debug_slow_fn:
            debug_slow_fn(
                f"layout switch click skipped pending refresh "
                f"mouse=({mouse_x:.0f},{mouse_y:.0f})"
            )
        return False

    manager._layout_pending_switch_click = {
        'geometry_key': geometry_key,
        'x': float(mouse_x),
        'y': float(mouse_y),
        'at': now,
    }

    view_key = manager._layout_cache.view_for_click(geometry_key, mouse_x, mouse_y)
    if debug_slow_fn:
        debug_slow_fn(
            f"layout switch click queued "
            f"mouse=({mouse_x:.0f},{mouse_y:.0f}) "
            f"cached_view={view_key or 'none'} "
            f"current={manager._current_layout_view_key or 'none'}"
        )
    if not view_key or view_key == manager._current_layout_view_key:
        if not manager._layout_refresh_requested:
            request_layout_refresh(manager, 'layout-switch-click')
        return False

    applied = apply_cached_layout(
        manager,
        geometry_key,
        view_key,
        mouse_x,
        mouse_y,
        sync_wheel_overlays_fn=sync_wheel_overlays_fn,
        check_hover_fn=check_hover_fn,
        debug_slow_fn=debug_slow_fn,
    )
    if applied:
        request_layout_refresh(manager, 'layout-cache-verify')
    return applied


def store_scanned_layout(
    manager,
    areas,
    *,
    layout_changed,
    debug_slow_fn=None,
):
    geometry_key = current_layout_geometry_key(manager)
    check_layout_scan(manager)
    if not geometry_key or not areas:
        return None

    previous_view_key = manager._current_layout_view_key
    view_key = manager._layout_cache.store_layout(geometry_key, areas)
    if view_key:
        manager._current_layout_view_key = view_key

    pending = manager._layout_pending_switch_click
    if pending and time.time() - pending.get('at', 0.0) > PENDING_SWITCH_CLICK_SECONDS:
        manager._layout_pending_switch_click = None
        pending = None

    if (
        layout_changed
        and pending
        and pending.get('geometry_key') == geometry_key
        and time.time() - pending.get('at', 0.0) <= PENDING_SWITCH_CLICK_SECONDS
        and not area_at_point(areas, pending.get('x', 0.0), pending.get('y', 0.0))
    ):
        if view_key and view_key != previous_view_key:
            manager._layout_cache.remember_click(
                geometry_key,
                pending['x'],
                pending['y'],
                view_key,
            )
            if debug_slow_fn:
                debug_slow_fn(
                    f"layout cache learned click view={view_key} "
                    f"mouse=({pending['x']:.0f},{pending['y']:.0f}) "
                    f"views={manager._layout_cache.cached_view_count(geometry_key)}"
                )
        elif debug_slow_fn:
            debug_slow_fn(
                f"layout cache skipped click learn unchanged view={view_key or 'none'} "
                f"mouse=({pending['x']:.0f},{pending['y']:.0f})"
            )
        manager._layout_pending_switch_click = None

    return view_key


def apply_cached_layout(
    manager,
    geometry_key,
    view_key,
    mouse_x,
    mouse_y,
    *,
    sync_wheel_overlays_fn,
    check_hover_fn,
    debug_slow_fn=None,
):
    cached_areas = manager._layout_cache.get_layout(geometry_key, view_key)
    if not cached_areas:
        return False

    new_signature = make_areas_signature(cached_areas)
    if new_signature == manager._areas_signature:
        manager._current_layout_view_key = view_key
        return False

    clear_runtime_target_cache(manager)
    manager.areas = cached_areas
    manager._areas_signature = new_signature
    manager._current_layout_view_key = view_key
    sync_wheel_overlays_fn(manager)
    check_hover_fn(mouse_x, mouse_y)
    if debug_slow_fn:
        debug_slow_fn(
            f"layout cache applied view={view_key} "
            f"mouse=({mouse_x:.0f},{mouse_y:.0f}) areas={len(cached_areas)}"
        )
    return True


def clear_hover_state(
    manager,
    *,
    clear_areas=False,
    clear_wheel_orbit_fn,
    release_param_drag_fn,
    release_wheel_drag_fn,
):
    clear_wheel_orbit_fn()
    release_param_drag_fn()
    release_wheel_drag_fn()
    manager._manual_wheel_drag = None
    clear_wheel_control_state(
        manager,
        clear_recent=True,
        clear_target_lock=True,
        clear_segment=True,
        clear_anchor=True,
        clear_diameter=True,
    )
    clear_hover_overlays(manager)
    manager.current_hover_area = None
    clear_wheel_control_state(
        manager,
        clear_handles_cache=True,
        clear_state_store=clear_areas,
    )
    if clear_areas:
        manager.areas = []
        manager._areas_signature = None


def show_hover_overlay_for_manager(
    manager,
    area,
    key,
    *,
    overlay_factory,
    detect_handle_raw_for_area_fn,
    debug_slow_fn=None,
):
    return show_hover_overlay(
        manager,
        area,
        key,
        overlay_factory,
        detect_handle_raw_for_area_fn,
        debug_slow_fn=debug_slow_fn,
    )


def active_locked_hover_area(manager):
    wheel_area = active_wheel_target_area(manager)
    if wheel_area:
        return wheel_area
    if manager.current_hover_area:
        return manager.current_hover_area
    return recent_wheel_area(manager)


def ensure_locked_hover_overlay_visible(manager, *, show_hover_overlay_fn):
    area = active_locked_hover_area(manager)
    if not area:
        hide_inactive_overlays(manager)
        return False
    key = area_key(area)
    if not key:
        hide_inactive_overlays(manager)
        return False
    manager.current_hover_area = area
    return show_hover_overlay_fn(area, key)


def is_davinci_ready_for_interaction(manager):
    if not manager.label_finder:
        manager._davinci_active = False
        manager._davinci_running = False
        return False

    try:
        manager._davinci_running = bool(manager.label_finder.is_app_running())
    except Exception:
        manager._davinci_running = False

    if not manager._davinci_running:
        manager._davinci_active = False
        return False

    try:
        manager._davinci_active = bool(manager.label_finder.is_frontmost())
    except Exception:
        manager._davinci_active = False

    return bool(manager._davinci_active)


def handle_davinci_state_change(
    manager,
    is_active,
    *,
    clear_hover_state_fn,
    request_layout_refresh_fn,
):
    manager._davinci_running = (
        manager.label_finder.is_app_running()
        if manager.label_finder
        else False
    )
    manager._davinci_active = is_active and manager._davinci_running
    if not is_active:
        clear_hover_state_fn(clear_areas=not manager._davinci_running)
    else:
        manager._last_state_update = 0.0
        request_layout_refresh_fn('frontmost')


def check_hover(
    manager,
    mouse_x,
    mouse_y,
    *,
    plugin_mouse_button_active_fn,
    left_mouse_button_down_fn,
    min_mouse_move_distance_px,
    is_ready_for_interaction_fn,
    clear_hover_state_fn,
    release_param_if_cursor_moved_fn,
    release_wheel_drag_fn,
    clear_wheel_orbit_fn,
    ensure_locked_hover_overlay_visible_fn,
    release_wheel_drag_if_idle_fn,
    release_wheel_orbit_if_cursor_moved_fn,
    show_hover_overlay_fn,
    on_hover_change_fn,
    debug_slow_fn=None,
    debug_callback_process_ms=0.0,
):
    started_at = time.perf_counter()
    if not is_ready_for_interaction_fn() or not manager.areas:
        clear_hover_state_fn()
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if debug_slow_fn and elapsed_ms >= debug_callback_process_ms:
            debug_slow_fn(f"hover check inactive {elapsed_ms:.1f}ms areas={len(manager.areas)}")
        return

    note_user_mouse_move(
        manager,
        mouse_x,
        mouse_y,
        plugin_mouse_button_active_fn=plugin_mouse_button_active_fn,
        left_mouse_button_down_fn=left_mouse_button_down_fn,
        min_distance_px=min_mouse_move_distance_px,
    )

    if manager._manual_wheel_drag:
        drag_area = manager._manual_wheel_drag.get('area')
        drag_key = manager._manual_wheel_drag.get('key')
        if drag_area and drag_key:
            manager.current_hover_area = drag_area
            hide_inactive_overlays(manager, drag_key)
            set_wheel_dot_hidden(manager, drag_area, True)
        return

    if manager._param_drag:
        if not release_param_if_cursor_moved_fn(mouse_x, mouse_y):
            return

    locked_wheel_area = active_wheel_target_area(manager)
    if (
        locked_wheel_area
        and locked_wheel_area.get('type') == 'wheel'
        and not area_contains_point(locked_wheel_area, mouse_x, mouse_y)
        and not plugin_mouse_button_active_fn()
        and not left_mouse_button_down_fn()
    ):
        if debug_slow_fn:
            debug_slow_fn(
                f"wheel target unlock outside {area_label(locked_wheel_area)} "
                f"mouse=({mouse_x:.0f},{mouse_y:.0f})"
            )
        release_wheel_drag_fn()
        clear_wheel_orbit_fn()
        clear_wheel_control_state(
            manager,
            clear_recent=True,
            clear_target_lock=True,
            clear_segment=True,
            clear_anchor=True,
            clear_diameter=True,
        )

    if is_hover_locked(manager):
        ensure_locked_hover_overlay_visible_fn()
        return

    if wheel_drag_state(manager):
        if not release_wheel_drag_if_idle_fn():
            return

    orbit = wheel_orbit_state(manager)
    if orbit and orbit.get('dragging'):
        if not release_wheel_orbit_if_cursor_moved_fn(mouse_x, mouse_y):
            return

    hovered_area = None
    for area in sorted(manager.areas, key=lambda item: item.get('priority', 0), reverse=True):
        if (
            area['x'] <= mouse_x <= area['x'] + area['w']
            and area['y'] <= mouse_y <= area['y'] + area['h']
        ):
            hovered_area = area
            break

    old_area = manager.current_hover_area
    old_key = area_key(old_area) if old_area else None
    new_key = area_key(hovered_area) if hovered_area else None

    if new_key != old_key:
        if old_area and old_area.get('type') == 'wheel':
            old_area_name = old_area.get('name')
            new_area_name = hovered_area.get('name') if hovered_area else None
            release_wheel_drag_fn()
            clear_wheel_orbit_fn()
            clear_wheel_control_state(
                manager,
                clear_recent=True,
                clear_target_lock=True,
                clear_segment=True,
                clear_anchor=True,
                clear_diameter=True,
            )
            if old_area_name and old_area_name != new_area_name:
                remove_wheel_handle(manager, old_area_name)

        old_name = area_label(old_area) if old_area else None
        new_name = area_label(hovered_area) if hovered_area else None
        hide_inactive_overlays(manager)
        manager.current_hover_area = hovered_area
        manager._pending_hover_overlay_key = None
        manager._pending_hover_overlay_at = 0.0
        if hovered_area and hovered_area.get('type') == 'wheel':
            clear_wheel_control_state(
                manager,
                clear_target_lock=True,
                clear_segment=True,
                clear_anchor=True,
                clear_diameter=True,
            )
            hovered_name = hovered_area.get('name')
            if hovered_name:
                remove_wheel_handle(manager, hovered_name)
        if hovered_area:
            show_hover_overlay_fn(hovered_area, new_key)
        if debug_slow_fn:
            debug_slow_fn(
                f"hover transition {old_name or 'None'} -> {new_name or 'None'} "
                f"mouse=({mouse_x:.0f},{mouse_y:.0f})"
            )
        on_hover_change_fn(area_label(hovered_area) if hovered_area else None)
        return

    if hovered_area:
        if not refresh_existing_hover_overlay(manager, hovered_area, new_key):
            show_hover_overlay_fn(hovered_area, new_key)
        return

    hide_inactive_overlays(manager)
    manager._pending_hover_overlay_key = None
    manager._pending_hover_overlay_at = 0.0
    return


__all__ = [
    'is_hover_locked',
    'lock_hover_for_param_dial',
    'lock_hover_for_wheel_dial',
    'note_param_dial_activity',
    'note_wheel_dial_activity',
    'make_areas_signature',
    'request_layout_refresh',
    'note_user_mouse_move',
    'can_refresh_layout',
    'layout_refresh_due',
    'clear_runtime_target_cache',
    'process_scheduled_layout_refresh',
    'current_layout_geometry_key',
    'note_layout_switch_click',
    'store_scanned_layout',
    'apply_cached_layout',
    'clear_hover_state',
    'show_hover_overlay_for_manager',
    'active_locked_hover_area',
    'ensure_locked_hover_overlay_visible',
    'is_davinci_ready_for_interaction',
    'handle_davinci_state_change',
    'check_hover',
]
