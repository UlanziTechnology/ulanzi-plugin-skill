"""Consolidated DaVinci manager wheel responsibilities."""

import time
from ..layout_scan_guard import note_layout_input
from ..config import WHEEL_SEGMENT_SESSION_SECONDS
from ..wheel_handle_detection_controller import detect_handle_for_manager, detect_handle_raw_for_manager_area
from ..param_drag_controller import release_param_drag, release_param_drag_after_idle, release_param_drag_if_cursor_moved, release_param_drag_if_idle, schedule_param_release_timer
from ..wheel_drag_release_basic import release_wheel_drag, release_wheel_drag_if_idle
from ..wheel_diameter import WheelDiameterRuntime, handle_wheel_diameter_rotate
from ..wheel_diameter_state_bindings import wheel_diameter_state_bindings
from ..wheel_dial_dispatch_controller import handle_wheel_dial_rotate
from ..wheel_legacy_closed_controller import handle_wheel_dial_rotate_closed
from ..wheel_legacy_segment_controller import handle_wheel_dial_rotate_segment
from ..wheel_orbit import WheelOrbitRuntime, handle_wheel_orbit_closed_loop
from ..wheel_orbit_release_controller import (
    clear_wheel_orbit,
    release_wheel_orbit_drag,
    release_wheel_orbit_if_cursor_moved,
    release_wheel_orbit_if_idle,
)
from ..wheel_orbit_state_bindings import wheel_orbit_state_bindings
from ..wheel_outer_anchor import WheelOuterAnchorRuntime, handle_wheel_outer_anchor_rotate
from ..wheel_outer_anchor_state_bindings import wheel_outer_anchor_state_bindings
from ..wheel_reset_controller import reset_current_wheel_to_center_action, reset_wheel_via_native_button
from .state import (
    wheel_handle_detection_state_callbacks,
    wheel_legacy_state_callbacks,
    wheel_release_state_callbacks,
    wheel_reset_state_callbacks,
)


def _wheel_dial_owner_is_recent(manager, now):
    owner = getattr(manager, '_wheel_dial_owner_context', None)
    owner_at = getattr(manager, '_wheel_dial_owner_at', 0.0)
    if not owner:
        return False
    if now - owner_at <= WHEEL_SEGMENT_SESSION_SECONDS:
        return True
    manager._wheel_dial_owner_context = None
    manager._wheel_dial_owner_at = 0.0
    manager._wheel_dial_owner_mode = None
    return False


def _claim_wheel_dial_owner(manager, action_context, now, mode):
    if not action_context:
        return
    manager._wheel_dial_owner_context = action_context
    manager._wheel_dial_owner_at = now
    manager._wheel_dial_owner_mode = mode


def _wheel_mode_from_event(is_hold, mode):
    return is_hold if mode is None else mode == 'diameter'


def _should_ignore_unconfigured_wheel_fallback(
    manager,
    *,
    mode,
    wheel_settings_explicit,
    now,
):
    if wheel_settings_explicit:
        return False
    if mode not in {'orbit', 'diameter'}:
        return False
    if manager.current_hover_area and manager.current_hover_area.get('type') == 'wheel':
        return False
    if _wheel_dial_owner_is_recent(manager, now):
        return False
    return True


def _dispatch_wheel_dial(
    manager,
    area,
    ticks,
    wheel_radial_mode,
    *,
    action_context,
    now,
    handle_wheel_dial_rotate_fn,
    debug_slow_fn,
):
    owner = getattr(manager, '_wheel_dial_owner_context', None)
    had_owner = bool(owner)
    previous_mode = getattr(manager, '_wheel_dial_owner_mode', None)
    mode_name = 'diameter' if wheel_radial_mode else 'orbit'
    if owner and action_context and action_context != owner and debug_slow_fn:
        debug_slow_fn(
            "dial wheel-owner-handoff "
            f"ticks={ticks} owner={owner} context={action_context} "
            f"from={previous_mode or 'unknown'} to={mode_name}"
        )
    _claim_wheel_dial_owner(manager, action_context, now, mode_name)
    moved = handle_wheel_dial_rotate_fn(area, ticks, wheel_radial_mode)
    if not moved and not had_owner:
        manager._wheel_dial_owner_context = None
        manager._wheel_dial_owner_at = 0.0
        manager._wheel_dial_owner_mode = None
    return moved


def retire_smooth_before_legacy(smooth_backend, reason):
    """Release smooth ownership before a legacy mouse operation.

    ``cancel(False)`` can mean either harmless observer retirement or native
    pointer cleanup still in flight. Reuse the backend's legacy gate to tell
    those states apart, and fail closed on an unexpected adapter error.
    """

    if smooth_backend is None:
        return True
    try:
        if smooth_backend.cancel(reason):
            return True
        run_legacy = getattr(smooth_backend, 'run_legacy_if_idle', None)
        return bool(callable(run_legacy) and run_legacy(lambda: True))
    except Exception:
        return False


def try_handle_manager_smooth_wheel_dial(
    manager,
    ticks,
    *,
    is_hold=False,
    mode=None,
    action_context=None,
    wheel_settings_explicit=False,
    smooth_backend,
    active_wheel_target_area_fn,
    wheel_drag_state_fn,
    wheel_orbit_state_fn,
    clear_wheel_control_state_fn,
    is_ready_for_interaction_fn,
    active_locked_hover_area_fn,
    note_wheel_dial_activity_fn,
    sensitivity=1.0,
    debug_slow_fn=None,
):
    """Try the lossless native path without stealing non-wheel controls.

    The tri-state return is intentional: ``None`` keeps the legacy queue for
    sliders, numeric controls, unsupported platforms, and an already-running legacy wheel
    gesture; ``False`` means the smooth path owned the wheel event but failed
    closed, so callers must not start a second mouse owner.
    """

    if smooth_backend is None:
        return None
    if ticks == 0:
        return False

    # Never transfer ownership in the middle of a legacy held gesture.
    if manager._param_drag or wheel_drag_state_fn(manager) or wheel_orbit_state_fn(manager):
        return None

    smooth_area = smooth_backend.active_area
    if smooth_area is None and not is_ready_for_interaction_fn():
        smooth_backend.cancel("davinci_not_ready")
        return False

    current = manager.current_hover_area
    if current is not None and current.get('type') != 'wheel':
        if smooth_area is None:
            return None

        # An armed controller deliberately survives its idle UP so another
        # wheel detent can reuse recognition. Once the real hover explicitly
        # selects a legacy target, retire that controller before queueing the
        # slider/numeric event; otherwise its long-lived ``armed`` state would
        # make ``run_legacy_if_idle`` reject every later callback.
        if retire_smooth_before_legacy(smooth_backend, "legacy_target"):
            # Only the bounded visual observer remains; it owns no pointer and
            # is safe to overlap the established slider implementation.
            return None
        # Native/pointer cleanup is still pending, so fail this tick closed
        # rather than create a second mouse owner.
        return False

    area = current if current and current.get('type') == 'wheel' else None
    if area is None and smooth_area is not None:
        area = smooth_area
    if area is None:
        area = active_wheel_target_area_fn(manager)
    if area is None:
        locked = active_locked_hover_area_fn()
        area = locked if locked and locked.get('type') == 'wheel' else None
    if area is None:
        return None

    now = time.time()
    if smooth_area is None and _should_ignore_unconfigured_wheel_fallback(
        manager,
        mode=mode,
        wheel_settings_explicit=wheel_settings_explicit,
        now=now,
    ):
        return False

    note_layout_input(manager)
    result = smooth_backend.try_submit(
        area,
        ticks,
        mode or ('diameter' if is_hold else 'orbit'),
        action_context,
        sensitivity,
    )
    if result is None:
        # Recognition and clean preflight failures deliberately fall back to
        # the established implementation.  They must leave its continuation
        # state completely intact.
        return None

    # These are legacy prediction caches rather than active mouse ownership.
    # Once the smooth path owns (or fails closed on) the event, prevent a
    # later legacy gesture from continuing against a stale anchor/diameter.
    clear_wheel_control_state_fn(
        manager,
        clear_segment=True,
        clear_anchor=True,
        clear_diameter=True,
    )
    if result:
        mode_name = mode or ('diameter' if is_hold else 'orbit')
        _claim_wheel_dial_owner(manager, action_context, now, mode_name)
        note_wheel_dial_activity_fn(area)
        if debug_slow_fn:
            debug_slow_fn(
                "smooth wheel accepted "
                f"target={area.get('name') or area.get('id') or 'unknown'} "
                f"mode={mode_name} ticks={ticks} context={action_context or 'none'}"
            )
    return bool(result)


def handle_manager_dial_rotate(
    manager,
    ticks,
    *,
    is_hold=False,
    mode=None,
    action_context=None,
    wheel_settings_explicit=False,
    param_dial_area_types,
    active_wheel_target_area_fn,
    wheel_drag_state_fn,
    wheel_orbit_state_fn,
    clear_wheel_control_state_fn,
    is_ready_for_interaction_fn,
    clear_hover_state_fn,
    move_param_drag_fn,
    active_locked_hover_area_fn,
    handle_wheel_dial_rotate_fn,
    clear_wheel_orbit_fn,
    release_wheel_drag_fn,
    release_param_drag_fn,
    handle_param_dial_drag_fn,
    debug_slow_fn=None,
):
    if not is_ready_for_interaction_fn():
        if not manager._davinci_running:
            clear_hover_state_fn(clear_areas=True)
        if debug_slow_fn:
            debug_slow_fn(
                "dial ignored not-ready "
                f"running={manager._davinci_running} "
                f"active={manager._davinci_active} "
                f"areas={len(manager.areas)}"
            )
        return False

    now = time.time()

    if manager._param_drag and not is_hold:
        return move_param_drag_fn(ticks)

    wheel_area = active_wheel_target_area_fn(manager)
    if (
        wheel_area
        and (
            wheel_drag_state_fn(manager)
            or wheel_orbit_state_fn(manager)
            or not manager.current_hover_area
            or manager.current_hover_area.get('type') == 'wheel'
        )
    ):
        if _should_ignore_unconfigured_wheel_fallback(
            manager,
            mode=mode,
            wheel_settings_explicit=wheel_settings_explicit,
            now=now,
        ):
            if debug_slow_fn:
                debug_slow_fn(
                    "dial ignored unconfigured-wheel-fallback "
                    f"ticks={ticks} mode={mode or 'auto'} "
                    f"context={action_context or 'none'}"
                )
            return False
        return _dispatch_wheel_dial(
            manager,
            wheel_area,
            ticks,
            _wheel_mode_from_event(is_hold, mode),
            action_context=action_context,
            now=now,
            handle_wheel_dial_rotate_fn=handle_wheel_dial_rotate_fn,
            debug_slow_fn=debug_slow_fn,
        )

    if not manager.current_hover_area:
        if manager._param_drag and not is_hold:
            return move_param_drag_fn(ticks)
        drag = wheel_drag_state_fn(manager)
        if drag:
            if _should_ignore_unconfigured_wheel_fallback(
                manager,
                mode=mode,
                wheel_settings_explicit=wheel_settings_explicit,
                now=now,
            ):
                if debug_slow_fn:
                    debug_slow_fn(
                        "dial ignored unconfigured-wheel-drag "
                        f"ticks={ticks} mode={mode or 'auto'} "
                        f"context={action_context or 'none'}"
                    )
                return False
            return _dispatch_wheel_dial(
                manager,
                drag['area'],
                ticks,
                _wheel_mode_from_event(is_hold, mode),
                action_context=action_context,
                now=now,
                handle_wheel_dial_rotate_fn=handle_wheel_dial_rotate_fn,
                debug_slow_fn=debug_slow_fn,
            )
        wheel_area = active_locked_hover_area_fn()
        if wheel_area and wheel_area.get('type') == 'wheel':
            if _should_ignore_unconfigured_wheel_fallback(
                manager,
                mode=mode,
                wheel_settings_explicit=wheel_settings_explicit,
                now=now,
            ):
                if debug_slow_fn:
                    debug_slow_fn(
                        "dial ignored unconfigured-wheel-lock "
                        f"ticks={ticks} mode={mode or 'auto'} "
                        f"context={action_context or 'none'}"
                    )
                return False
            return _dispatch_wheel_dial(
                manager,
                wheel_area,
                ticks,
                _wheel_mode_from_event(is_hold, mode),
                action_context=action_context,
                now=now,
                handle_wheel_dial_rotate_fn=handle_wheel_dial_rotate_fn,
                debug_slow_fn=debug_slow_fn,
            )
        if debug_slow_fn:
            debug_slow_fn(
                "dial ignored no-hover "
                f"ticks={ticks} mode={mode or 'auto'} "
                f"areas={len(manager.areas)} "
                f"recent={'yes' if active_locked_hover_area_fn() else 'no'}"
            )
        return False

    area_type = manager.current_hover_area.get('type')

    if area_type in param_dial_area_types:
        clear_wheel_orbit_fn()
        release_wheel_drag_fn()
        clear_wheel_control_state_fn(
            manager,
            clear_recent=True,
            clear_target_lock=True,
            clear_segment=True,
            clear_anchor=True,
            clear_diameter=True,
        )
        if is_hold:
            release_param_drag_fn()
            return False

        return handle_param_dial_drag_fn(manager.current_hover_area, ticks)

    release_param_drag_fn()

    if area_type != 'wheel':
        clear_wheel_orbit_fn()
        release_wheel_drag_fn()
        clear_wheel_control_state_fn(
            manager,
            clear_recent=True,
            clear_target_lock=True,
            clear_anchor=True,
            clear_diameter=True,
        )
        if debug_slow_fn:
            debug_slow_fn(
                "dial ignored non-wheel "
                f"type={area_type or 'none'} ticks={ticks} mode={mode or 'auto'}"
            )
        return False

    return _dispatch_wheel_dial(
        manager,
        manager.current_hover_area,
        ticks,
        _wheel_mode_from_event(is_hold, mode),
        action_context=action_context,
        now=now,
        handle_wheel_dial_rotate_fn=handle_wheel_dial_rotate_fn,
        debug_slow_fn=debug_slow_fn,
    )


class ManagerHandleDetectionBindings:
    def __init__(
        self,
        manager,
        *,
        detect_wheel_circle_in_area_fn,
        detect_handle_in_area_fn,
        is_ready_for_interaction_fn,
        clear_hover_state_fn,
        davinci_running_fn,
        debug_slow_fn=None,
    ):
        self.manager = manager
        self.detect_wheel_circle_in_area_fn = detect_wheel_circle_in_area_fn
        self.detect_handle_in_area_fn = detect_handle_in_area_fn
        self.is_ready_for_interaction_fn = is_ready_for_interaction_fn
        self.clear_hover_state_fn = clear_hover_state_fn
        self.davinci_running_fn = davinci_running_fn
        self.debug_slow_fn = debug_slow_fn

    def detect_handle(self, area_name):
        return detect_handle_for_manager(
            area_name,
            state_callbacks=wheel_handle_detection_state_callbacks(self.manager),
            detect_wheel_circle_in_area_fn=self.detect_wheel_circle_in_area_fn,
            detect_handle_in_area_fn=self.detect_handle_in_area_fn,
            is_davinci_ready_for_interaction_fn=self.is_ready_for_interaction_fn,
            clear_hover_state_fn=self.clear_hover_state_fn,
            davinci_running_fn=self.davinci_running_fn,
            debug_slow_fn=self.debug_slow_fn,
        )

    def detect_raw_for_area(self, area, expected_handle=None, expected_axis=None):
        return detect_handle_raw_for_manager_area(
            area,
            detect_wheel_circle_in_area_fn=self.detect_wheel_circle_in_area_fn,
            detect_handle_in_area_fn=self.detect_handle_in_area_fn,
            is_davinci_ready_for_interaction_fn=self.is_ready_for_interaction_fn,
            expected_handle=expected_handle,
            expected_axis=expected_axis,
        )


class ManagerReleaseBindings:
    def __init__(
        self,
        manager,
        *,
        mouse_drag_end_fn,
        get_cursor_position_fn=None,
        set_cursor_position_fn=None,
        debug_slow_fn=None,
    ):
        self.manager = manager
        self.mouse_drag_end_fn = mouse_drag_end_fn
        self.get_cursor_position_fn = get_cursor_position_fn
        self.set_cursor_position_fn = set_cursor_position_fn
        self.debug_slow_fn = debug_slow_fn

    def schedule_param_release_timer(self, delay=None):
        return schedule_param_release_timer(
            self.manager,
            self.release_param_drag_if_idle,
            delay=delay,
        )

    def release_param_drag(self, restore_cursor=True):
        return release_param_drag(
            self.manager,
            restore_cursor,
            self.mouse_drag_end_fn,
            set_cursor_position_fn=self.set_cursor_position_fn,
            debug_slow_fn=self.debug_slow_fn,
        )

    def release_wheel_drag(self):
        return release_wheel_drag(
            wheel_release_state_callbacks(self.manager),
            self.mouse_drag_end_fn,
            set_cursor_position_fn=self.set_cursor_position_fn,
            debug_slow_fn=self.debug_slow_fn,
        )

    def release_wheel_orbit_drag(self, restore_cursor=True):
        return release_wheel_orbit_drag(
            wheel_release_state_callbacks(self.manager),
            self.mouse_drag_end_fn,
            restore_cursor=restore_cursor,
            set_cursor_position_fn=self.set_cursor_position_fn,
            debug_slow_fn=self.debug_slow_fn,
        )

    def clear_wheel_orbit(self):
        return clear_wheel_orbit(
            wheel_release_state_callbacks(self.manager),
            self.release_wheel_orbit_drag,
        )

    def release_param_drag_after_idle(self):
        return release_param_drag_after_idle(
            self.manager,
            self.get_cursor_position_fn,
            self.mouse_drag_end_fn,
            set_cursor_position_fn=self.set_cursor_position_fn,
            debug_slow_fn=self.debug_slow_fn,
        )

    def release_param_drag_if_idle(self):
        return release_param_drag_if_idle(
            self.manager,
            self.release_param_drag_after_idle,
            self.schedule_param_release_timer,
        )

    def release_wheel_drag_if_idle(self):
        return release_wheel_drag_if_idle(
            wheel_release_state_callbacks(self.manager),
            self.release_wheel_drag,
        )

    def release_wheel_orbit_if_idle(self):
        return release_wheel_orbit_if_idle(
            wheel_release_state_callbacks(self.manager),
            self.release_wheel_orbit_drag,
        )

    def release_param_drag_if_cursor_moved(self, mouse_x, mouse_y):
        return release_param_drag_if_cursor_moved(
            self.manager,
            mouse_x,
            mouse_y,
            self.release_param_drag,
            debug_slow_fn=self.debug_slow_fn,
        )

    def release_wheel_orbit_if_cursor_moved(self, mouse_x, mouse_y):
        return release_wheel_orbit_if_cursor_moved(
            wheel_release_state_callbacks(self.manager),
            mouse_x,
            mouse_y,
            self.release_wheel_orbit_drag,
            debug_slow_fn=self.debug_slow_fn,
        )


class ManagerWheelMotionBindings:
    def __init__(
        self,
        manager,
        *,
        detect_wheel_circle_in_area_fn,
        detect_handle_fn,
        detect_raw_handle_fn,
        mouse_drag_begin_fn,
        mouse_drag_move_by_path_fn,
        mouse_drag_move_path_fn,
        mouse_drag_move_absolute_path_fn,
        mouse_drag_end_fn,
        get_cursor_position_fn,
        clear_wheel_orbit_fn,
        release_param_drag_fn,
        release_wheel_drag_fn,
        release_wheel_orbit_drag_fn,
        note_wheel_dial_activity_fn,
        refresh_wheel_overlay_state_fn,
        clear_wheel_anchor_state_fn,
        set_cursor_position_fn=None,
        pump_win32_messages_fn=None,
        debug_slow_fn=None,
    ):
        self.manager = manager
        self.detect_wheel_circle_in_area_fn = detect_wheel_circle_in_area_fn
        self.detect_handle_fn = detect_handle_fn
        self.detect_raw_handle_fn = detect_raw_handle_fn
        self.mouse_drag_begin_fn = mouse_drag_begin_fn
        self.mouse_drag_move_by_path_fn = mouse_drag_move_by_path_fn
        self.mouse_drag_move_path_fn = mouse_drag_move_path_fn
        self.mouse_drag_move_absolute_path_fn = mouse_drag_move_absolute_path_fn
        self.mouse_drag_end_fn = mouse_drag_end_fn
        self.get_cursor_position_fn = get_cursor_position_fn
        self.clear_wheel_orbit_fn = clear_wheel_orbit_fn
        self.release_param_drag_fn = release_param_drag_fn
        self.release_wheel_drag_fn = release_wheel_drag_fn
        self.release_wheel_orbit_drag_fn = release_wheel_orbit_drag_fn
        self.note_wheel_dial_activity_fn = note_wheel_dial_activity_fn
        self.refresh_wheel_overlay_state_fn = refresh_wheel_overlay_state_fn
        manager._refresh_wheel_overlay_state_fn = refresh_wheel_overlay_state_fn
        self.clear_wheel_anchor_state_fn = clear_wheel_anchor_state_fn
        self.set_cursor_position_fn = set_cursor_position_fn
        self.pump_win32_messages_fn = pump_win32_messages_fn
        self.debug_slow_fn = debug_slow_fn
        self._diameter_runtime = WheelDiameterRuntime(
            state=wheel_diameter_state_bindings(manager),
            detect_wheel_circle_in_area=detect_wheel_circle_in_area_fn,
            detect_handle=detect_handle_fn,
            detect_raw_handle=detect_raw_handle_fn,
            mouse_drag_begin=mouse_drag_begin_fn,
            mouse_drag_move_absolute_path=mouse_drag_move_absolute_path_fn,
            mouse_drag_end=mouse_drag_end_fn,
            get_cursor_position=get_cursor_position_fn,
            clear_wheel_orbit=clear_wheel_orbit_fn,
            release_param_drag=release_param_drag_fn,
            release_wheel_drag=release_wheel_drag_fn,
            pump_overlay_messages=pump_win32_messages_fn,
            debug_slow=debug_slow_fn,
        )
        self._outer_anchor_runtime = WheelOuterAnchorRuntime(
            state=wheel_outer_anchor_state_bindings(manager),
            detect_wheel_circle_in_area=detect_wheel_circle_in_area_fn,
            detect_handle=detect_handle_fn,
            detect_raw_handle=detect_raw_handle_fn,
            mouse_drag_begin=mouse_drag_begin_fn,
            mouse_drag_move_absolute_path=mouse_drag_move_absolute_path_fn,
            mouse_drag_end=mouse_drag_end_fn,
            get_cursor_position=get_cursor_position_fn,
            clear_wheel_orbit=clear_wheel_orbit_fn,
            release_param_drag=release_param_drag_fn,
            release_wheel_drag=release_wheel_drag_fn,
            set_cursor_position=set_cursor_position_fn,
            pump_overlay_messages=pump_win32_messages_fn,
            debug_slow=debug_slow_fn,
        )
        self._orbit_runtime = WheelOrbitRuntime(
            state=wheel_orbit_state_bindings(manager),
            mouse_drag_begin=mouse_drag_begin_fn,
            mouse_drag_move_path=mouse_drag_move_path_fn,
            mouse_drag_move_by_path=mouse_drag_move_by_path_fn,
            get_cursor_position=get_cursor_position_fn,
            detect_handle=detect_handle_fn,
            detect_raw_handle=detect_raw_handle_fn,
            clear_wheel_orbit=clear_wheel_orbit_fn,
            release_param_drag=release_param_drag_fn,
            release_wheel_drag=release_wheel_drag_fn,
            release_wheel_orbit_drag=release_wheel_orbit_drag_fn,
        )

    @property
    def sensitivity(self):
        return self.manager.sensitivity

    def handle_closed(self, area, ticks):
        return handle_wheel_dial_rotate_closed(
            area,
            ticks,
            self.detect_wheel_circle_in_area_fn,
            self.detect_handle_fn,
            self.mouse_drag_begin_fn,
            self.mouse_drag_move_by_path_fn,
            self.mouse_drag_end_fn,
            self.get_cursor_position_fn,
            self.release_wheel_drag_fn,
            wheel_legacy_state_callbacks(self.manager),
            self.sensitivity,
            self.set_cursor_position_fn,
        )

    def handle_orbit_closed_loop(self, area, ticks):
        return handle_wheel_orbit_closed_loop(
            area,
            ticks,
            self._orbit_runtime,
            self.sensitivity,
        )

    def handle_outer_anchor_rotate(self, area, ticks):
        return handle_wheel_outer_anchor_rotate(
            area,
            ticks,
            self._outer_anchor_runtime,
            self.sensitivity,
        )

    def handle_segment(self, area, ticks):
        return handle_wheel_dial_rotate_segment(
            area,
            ticks,
            self.detect_wheel_circle_in_area_fn,
            self.detect_handle_fn,
            self.mouse_drag_begin_fn,
            self.mouse_drag_move_by_path_fn,
            self.mouse_drag_end_fn,
            self.get_cursor_position_fn,
            self.detect_raw_handle_fn,
            self.clear_wheel_orbit_fn,
            self.release_param_drag_fn,
            self.release_wheel_drag_fn,
            self.handle_diameter_rotate,
            wheel_legacy_state_callbacks(self.manager),
            self.sensitivity,
            self.set_cursor_position_fn,
            self.debug_slow_fn,
        )

    def handle_diameter_rotate(self, area, ticks):
        return handle_wheel_diameter_rotate(
            area,
            ticks,
            self._diameter_runtime,
            self.sensitivity,
        )

    def handle_dial_rotate(self, area, ticks, is_hold):
        return handle_wheel_dial_rotate(
            area,
            ticks,
            is_hold,
            outer_anchor_rotate_fn=self.handle_outer_anchor_rotate,
            diameter_rotate_fn=self.handle_diameter_rotate,
            note_wheel_dial_activity_fn=self.note_wheel_dial_activity_fn,
            refresh_wheel_overlay_state_fn=self.refresh_wheel_overlay_state_fn,
            clear_wheel_anchor_state_fn=self.clear_wheel_anchor_state_fn,
        )


class ManagerWheelResetBindings:
    def __init__(
        self,
        manager,
        *,
        detect_wheel_circle_in_area_fn,
        detect_handle_fn,
        mouse_click_fn,
        mouse_drag_begin_fn,
        mouse_drag_move_path_fn,
        mouse_drag_end_fn,
        get_cursor_position_fn,
        release_param_drag_fn,
        release_wheel_drag_fn,
        is_ready_for_interaction_fn,
        clear_hover_state_fn,
        davinci_running_fn,
        set_cursor_position_fn=None,
    ):
        self.manager = manager
        self.detect_wheel_circle_in_area_fn = detect_wheel_circle_in_area_fn
        self.detect_handle_fn = detect_handle_fn
        self.mouse_click_fn = mouse_click_fn
        self.mouse_drag_begin_fn = mouse_drag_begin_fn
        self.mouse_drag_move_path_fn = mouse_drag_move_path_fn
        self.mouse_drag_end_fn = mouse_drag_end_fn
        self.get_cursor_position_fn = get_cursor_position_fn
        self.release_param_drag_fn = release_param_drag_fn
        self.release_wheel_drag_fn = release_wheel_drag_fn
        self.is_ready_for_interaction_fn = is_ready_for_interaction_fn
        self.clear_hover_state_fn = clear_hover_state_fn
        self.davinci_running_fn = davinci_running_fn
        self.set_cursor_position_fn = set_cursor_position_fn

    def reset_via_native_button(self, area):
        return reset_wheel_via_native_button(
            area,
            wheel_reset_state_callbacks(self.manager),
            self.detect_wheel_circle_in_area_fn,
            self.mouse_click_fn,
            self.get_cursor_position_fn,
            self.set_cursor_position_fn,
        )

    def reset_current_wheel_to_center(self):
        return reset_current_wheel_to_center_action(
            wheel_reset_state_callbacks(self.manager),
            self.detect_wheel_circle_in_area_fn,
            self.detect_handle_fn,
            self.mouse_click_fn,
            self.mouse_drag_begin_fn,
            self.mouse_drag_move_path_fn,
            self.mouse_drag_end_fn,
            self.get_cursor_position_fn,
            self.release_param_drag_fn,
            self.release_wheel_drag_fn,
            self.is_ready_for_interaction_fn,
            self.clear_hover_state_fn,
            self.davinci_running_fn,
            self.set_cursor_position_fn,
        )


__all__ = [
    'handle_manager_dial_rotate',
    'try_handle_manager_smooth_wheel_dial',
    'retire_smooth_before_legacy',
    'ManagerHandleDetectionBindings',
    'ManagerReleaseBindings',
    'ManagerWheelMotionBindings',
    'ManagerWheelResetBindings',
]
