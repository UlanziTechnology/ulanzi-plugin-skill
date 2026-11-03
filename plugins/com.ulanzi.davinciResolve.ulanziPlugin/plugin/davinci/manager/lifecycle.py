"""Consolidated DaVinci manager lifecycle responsibilities."""

import time
import traceback
from functools import wraps

from ..layout_cache import LayoutCache
from ..layout_scan_guard import check_layout_scan
from ..wheel_state_store import WheelStateStore
from .hover import (
    clear_runtime_target_cache,
    make_areas_signature,
    store_scanned_layout,
)


def initialize_manager_fields(manager):
    manager.qt_app = None
    manager.label_finder = None
    manager.areas = []
    manager.overlays = {}
    manager.handles = {}
    manager.monitor_thread = None
    manager.is_monitoring = False
    manager.action_contexts = set()
    manager.sensitivity = 1.0
    manager.current_hover_area = None
    manager.update_timer = None
    manager._on_hover_callback = None
    manager._davinci_active = False
    manager._davinci_running = False
    manager._last_state_update = 0
    manager._param_drag = None
    manager._wheel_drag = None
    manager._hover_lock_until = 0.0
    manager._wheel_orbit = None
    manager._last_wheel_area = None
    manager._last_wheel_at = 0.0
    manager._wheel_target_lock_area = None
    manager._wheel_target_lock_key = None
    manager._wheel_target_lock_until = 0.0
    manager._wheel_segment_state = None
    manager._wheel_anchor_state = None
    manager._wheel_diameter_state = None
    manager._wheel_diameter_axis_lock = None
    manager._wheel_state_store = WheelStateStore()
    manager._layout_cache = LayoutCache()
    manager._current_layout_view_key = None
    manager._layout_pending_switch_click = None
    manager._areas_signature = None
    manager._param_dial_pixel_residue = 0.0
    manager._param_dial_residue_key = None
    manager._param_release_timer = None
    manager._last_param_dial_activity_at = 0.0
    manager._last_wheel_dial_activity_at = 0.0
    manager._layout_input_epoch = 0
    manager._last_layout_input_at = 0.0
    manager._layout_scan_checkpoint = None
    manager._wheel_dial_owner_context = None
    manager._wheel_dial_owner_at = 0.0
    manager._wheel_dial_owner_mode = None
    manager._hover_visible_key = None
    manager._pending_hover_overlay_key = None
    manager._pending_hover_overlay_at = 0.0
    manager._tourbox_probe_state = None
    manager._smooth_wheel_backend = None
    manager._manual_wheel_drag = None
    manager._last_user_mouse_move_at = 0.0
    manager._last_user_mouse_pos = None
    manager._last_layout_refresh_mouse_move_at = 0.0
    manager._layout_refresh_requested = False
    manager._layout_refresh_reason = None
    manager._qt_callback_guards = []


def _guard_qt_callback(callback, name, *, debug_slow_fn=None):
    @wraps(callback)
    def guarded(*args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except Exception:
            message = f"[qt-callback] {name} failed"
            print(message, flush=True)
            traceback.print_exc()
            if debug_slow_fn:
                try:
                    debug_slow_fn(message)
                except Exception:
                    traceback.print_exc()
            return None

    return guarded


def initialize_manager(
    manager,
    *,
    davinci_available,
    davinci_dependency_message,
    overlay_available,
    is_mac,
    is_screen_locked_fn,
    ax_is_process_trusted_fn,
    qapplication_cls,
    argv,
    label_finder_factory,
    sync_wheel_overlays_fn,
):
    if not davinci_available:
        return False, davinci_dependency_message or "DaVinci dependency unavailable"

    if not overlay_available:
        return False, "Overlay UI unavailable"

    if is_mac and is_screen_locked_fn and is_screen_locked_fn():
        return False, "macOS screen is locked"

    if is_mac and ax_is_process_trusted_fn and not ax_is_process_trusted_fn():
        return False, "Accessibility permission required"

    try:
        print("[init] preparing Overlay UI...", flush=True)
        manager.qt_app = qapplication_cls.instance()
        if not manager.qt_app:
            manager.qt_app = qapplication_cls(argv)

        if is_mac:
            try:
                from AppKit import (
                    NSApplication,
                    NSApplicationActivationPolicyProhibited,
                )

                NSApplication.sharedApplication().setActivationPolicy_(
                    NSApplicationActivationPolicyProhibited
                )
            except Exception as exc:
                print(f"macOS background UI policy failed: {exc}", flush=True)

        print("[init] initializing DaVinci window access...", flush=True)
        manager.label_finder = label_finder_factory()
        ok, err = manager.label_finder.init_ax()
        if not ok:
            return False, f"AX initialization failed: {err}"

        print("[init] finding Color Wheels labels...", flush=True)
        labels = manager.label_finder.find_labels()
        if not labels:
            print("Color Wheels labels not found; trying to switch to DaVinci Color page...")
            switched, switch_message = manager.label_finder.activate_color_page()
            print(switch_message)
            if switched:
                print("[init] finding Color Wheels labels again...", flush=True)
                labels = manager.label_finder.find_labels()

        print(f"[init] calculating selectable areas labels={len(labels)}...", flush=True)
        manager.areas = manager.label_finder.calculate_wheel_areas()
        manager._areas_signature = make_areas_signature(manager.areas)
        store_scanned_layout(manager, manager.areas, layout_changed=True)
        if not manager.areas:
            print("[init] collecting diagnostic texts...", flush=True)
            samples = manager.label_finder.get_diagnostic_texts()
            hint = "Please switch DaVinci to the Color page and open Primaries controls."
            if samples:
                return False, (
                    "No supported Primaries controls found. "
                    f"Current visible texts: {', '.join(samples)}. {hint}"
                )
            return False, f"No supported Primaries controls found. {hint}"

        print(f"[init] preparing Overlay targets={len(manager.areas)}...", flush=True)
        sync_wheel_overlays_fn(manager)

        print(f"Initialization succeeded: {len(manager.areas)} areas")
        return True, "Initialization succeeded"

    except Exception as exc:
        return False, f"Initialization error: {exc}"


def start_monitoring(
    manager,
    *,
    on_hover_callback=None,
    monitor_thread_factory,
    pyqt_available,
    timer_factory,
    left_button_immediate_callback,
    check_hover_fn,
    left_button_change_fn,
    davinci_state_change_fn,
    scheduled_layout_refresh_fn,
    debug_slow_fn=None,
    diagnostics_enabled=False,
    diagnostics_message=None,
):
    if on_hover_callback is not None:
        manager._on_hover_callback = on_hover_callback

    if manager.is_monitoring:
        return

    if not manager.label_finder or not manager.areas:
        if debug_slow_fn:
            debug_slow_fn("start monitoring skipped: DaVinci manager is not initialized")
        return

    manager.is_monitoring = True
    manager._davinci_active = manager.label_finder.is_frontmost()
    manager._davinci_running = manager.label_finder.is_app_running()
    manager._last_state_update = time.time()

    guarded_immediate = _guard_qt_callback(
        left_button_immediate_callback,
        "left_button_immediate",
        debug_slow_fn=debug_slow_fn,
    )
    guarded_hover = _guard_qt_callback(
        check_hover_fn,
        "position_changed",
        debug_slow_fn=debug_slow_fn,
    )
    guarded_left_button = _guard_qt_callback(
        left_button_change_fn,
        "left_button_changed",
        debug_slow_fn=debug_slow_fn,
    )
    guarded_davinci_state = _guard_qt_callback(
        davinci_state_change_fn,
        "davinci_state_changed",
        debug_slow_fn=debug_slow_fn,
    )
    guarded_layout_refresh = _guard_qt_callback(
        scheduled_layout_refresh_fn,
        "scheduled_layout_refresh",
        debug_slow_fn=debug_slow_fn,
    )
    manager._qt_callback_guards = [
        guarded_immediate,
        guarded_hover,
        guarded_left_button,
        guarded_davinci_state,
        guarded_layout_refresh,
    ]

    manager.monitor_thread = monitor_thread_factory(manager.label_finder)
    manager.monitor_thread.left_button_immediate_callback = guarded_immediate
    manager.monitor_thread.position_changed.connect(guarded_hover)
    manager.monitor_thread.left_button_changed.connect(guarded_left_button)
    manager.monitor_thread.davinci_state_changed.connect(guarded_davinci_state)
    manager.monitor_thread.start()

    if pyqt_available:
        manager.update_timer = timer_factory()
        manager.update_timer.timeout.connect(guarded_layout_refresh)
        manager.update_timer.start(100)

    if diagnostics_enabled and debug_slow_fn and diagnostics_message:
        debug_slow_fn(diagnostics_message)

    print("监控已启动")


def stop_monitoring(
    manager,
    *,
    clear_wheel_orbit_fn,
    release_param_drag_fn,
    release_wheel_drag_fn,
):
    if not manager.is_monitoring and not manager.monitor_thread and not manager.update_timer:
        return

    manager.is_monitoring = False
    manager._davinci_active = False
    manager._davinci_running = False
    clear_wheel_orbit_fn()
    release_param_drag_fn()
    release_wheel_drag_fn()
    manager._manual_wheel_drag = None

    if manager.monitor_thread:
        manager.monitor_thread.stop()
        manager.monitor_thread = None

    if manager.update_timer:
        manager.update_timer.stop()
        manager.update_timer = None

    manager._qt_callback_guards = []

    print("监控已停止")


def process_manager_events(
    manager,
    *,
    pyqt_available,
    win32_overlay_available,
    pump_win32_messages_fn,
    process_overlay_events_fn,
    release_param_if_idle_fn,
    release_wheel_if_idle_fn,
    release_orbit_if_idle_fn,
    scheduled_layout_refresh_fn,
):
    if pyqt_available and manager.qt_app:
        manager.qt_app.processEvents()
    if win32_overlay_available:
        pump_win32_messages_fn()

    if not pyqt_available:
        process_overlay_events_fn()

    release_param_if_idle_fn()
    release_wheel_if_idle_fn()
    release_orbit_if_idle_fn()

    scheduled_layout_refresh_fn()


def cleanup_manager(
    manager,
    *,
    clear_wheel_control_state_fn,
    clear_wheel_handles_fn,
    clear_wheel_orbit_fn,
    release_param_drag_fn,
    release_wheel_drag_fn,
    stop_monitoring_fn,
):
    clear_wheel_orbit_fn()
    release_param_drag_fn()
    release_wheel_drag_fn()
    clear_wheel_control_state_fn(
        manager,
        clear_recent=True,
        clear_segment=True,
        clear_diameter=True,
    )
    manager._tourbox_probe_state = None
    stop_monitoring_fn()
    for overlay in manager.overlays.values():
        overlay.hide()
        overlay.deleteLater()
    manager.overlays.clear()
    clear_wheel_handles_fn(manager)


def update_manager_state(
    manager,
    *,
    is_windows,
    get_cursor_position_fn,
    sync_wheel_overlays_fn,
    clear_hover_state_fn,
    check_hover_fn,
    debug_slow_fn=None,
    debug_state_check_ms=0.0,
    debug_update_state_ms=0.0,
):
    started_at = time.perf_counter()
    check_layout_scan(manager)
    if not manager.label_finder or not manager.label_finder.target_app:
        clear_hover_state_fn(clear_areas=True)
        return

    running_started_at = time.perf_counter()
    manager._davinci_running = manager.label_finder.is_app_running()
    running_ms = (time.perf_counter() - running_started_at) * 1000.0
    if debug_slow_fn and running_ms >= debug_state_check_ms:
        debug_slow_fn(f"is_app_running {running_ms:.1f}ms running={manager._davinci_running}")
    if not manager._davinci_running:
        manager._davinci_active = False
        clear_hover_state_fn(clear_areas=True)
        return

    front_started_at = time.perf_counter()
    is_active = manager.label_finder.is_frontmost()
    front_ms = (time.perf_counter() - front_started_at) * 1000.0
    if debug_slow_fn and front_ms >= debug_state_check_ms:
        debug_slow_fn(f"is_frontmost {front_ms:.1f}ms active={is_active}")
    manager._davinci_active = is_active

    if not is_active:
        clear_hover_state_fn()
        return

    labels_started_at = time.perf_counter()
    check_layout_scan(manager)
    labels = manager.label_finder.find_labels()
    check_layout_scan(manager)
    labels_ms = (time.perf_counter() - labels_started_at) * 1000.0
    if debug_slow_fn and labels_ms >= debug_update_state_ms:
        debug_slow_fn(f"find labels {labels_ms:.1f}ms labels={len(labels)}")
    if labels or manager.label_finder.is_app_running():
        areas_started_at = time.perf_counter()
        new_areas = manager.label_finder.calculate_wheel_areas()
        check_layout_scan(manager)
        new_signature = make_areas_signature(new_areas)
        layout_changed = new_signature != manager._areas_signature
        view_key = store_scanned_layout(
            manager,
            new_areas,
            layout_changed=layout_changed,
            debug_slow_fn=debug_slow_fn,
        )
        manager.areas = new_areas
        manager._areas_signature = new_signature
        areas_ms = (time.perf_counter() - areas_started_at) * 1000.0
        if debug_slow_fn and areas_ms >= debug_update_state_ms:
            debug_slow_fn(
                f"calculate areas {areas_ms:.1f}ms "
                f"areas={len(manager.areas)} view={view_key}"
            )
        sync_wheel_overlays_fn(manager)
        if layout_changed:
            clear_runtime_target_cache(manager)
            mouse_x, mouse_y = get_cursor_position_fn()
            if debug_slow_fn:
                debug_slow_fn(
                    f"layout refreshed; rematching hover at=({mouse_x:.0f},{mouse_y:.0f})"
                )
            check_hover_fn(mouse_x, mouse_y)

    total_ms = (time.perf_counter() - started_at) * 1000.0
    if debug_slow_fn and total_ms >= debug_update_state_ms:
        debug_slow_fn(
            f"update state total {total_ms:.1f}ms "
            f"active={manager._davinci_active} areas={len(manager.areas)}"
        )


__all__ = [
    'initialize_manager_fields',
    'initialize_manager',
    'start_monitoring',
    'stop_monitoring',
    'process_manager_events',
    'cleanup_manager',
    'update_manager_state',
]
