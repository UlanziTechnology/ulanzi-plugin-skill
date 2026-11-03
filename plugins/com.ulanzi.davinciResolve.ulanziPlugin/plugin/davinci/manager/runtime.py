"""Consolidated DaVinci manager runtime responsibilities."""

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Optional
from .wheel import handle_manager_dial_rotate, retire_smooth_before_legacy, try_handle_manager_smooth_wheel_dial
from .wheel import ManagerHandleDetectionBindings
from .hover import active_locked_hover_area, check_hover, clear_hover_state, ensure_locked_hover_overlay_visible, handle_davinci_state_change, is_davinci_ready_for_interaction, show_hover_overlay_for_manager
from .hover import lock_hover_for_param_dial, note_param_dial_activity as manager_note_param_dial_activity, note_wheel_dial_activity as manager_note_wheel_dial_activity
from .lifecycle import initialize_manager, initialize_manager_fields
from .hover import note_layout_switch_click
from .hover import can_refresh_layout, layout_refresh_due, process_scheduled_layout_refresh, request_layout_refresh
from .lifecycle import cleanup_manager, process_manager_events, start_monitoring as start_manager_monitoring, stop_monitoring as stop_manager_monitoring
from .wheel import ManagerReleaseBindings
from .lifecycle import update_manager_state
from .wheel import ManagerWheelMotionBindings
from .wheel import ManagerWheelResetBindings
from ..param_drag_controller import handle_param_dial_drag, move_param_drag
from ..wheel_manual_drag_controller import begin_manual_wheel_drag, begin_manual_wheel_drag_immediate, end_manual_wheel_drag, handle_manual_wheel_drag_button_change
from ..wheel_overlay_controller import refresh_wheel_overlay_state, sync_wheel_overlays
from ..wheel_state_manager import active_wheel_target_area, clear_wheel_anchor_state, clear_wheel_control_state, clear_wheel_handles, recent_wheel_area, wheel_drag_state, wheel_orbit_state
from .state import wheel_manual_drag_state_callbacks
from ..wheel_reset_visual_feedback import WheelResetVisualFeedback


@dataclass(frozen=True)
class DaVinciManagerRuntime:
    """Platform and UI services required by the manager."""

    config: Any
    davinci_available: bool
    davinci_dependency_message: Optional[str]
    overlay_available: bool
    is_mac: bool
    is_windows: bool
    win32_available: bool
    win32_overlay_available: bool
    overlay_force_win32_native: bool
    pyqt_available: bool
    qapplication_cls: Any
    qtimer_cls: Any
    argv: list
    label_finder_factory: Callable
    monitor_thread_factory: Callable
    overlay_factory: Callable
    platform_mouse_input: Any
    platform_mouse_actions: Any
    wheel_detection_adapter: Any
    plugin_mouse_button_state: Any
    pump_win32_messages: Callable
    process_overlay_events: Callable
    is_left_mouse_button_down: Callable
    is_mac_screen_locked: Optional[Callable]
    ax_is_process_trusted: Optional[Callable]
    debug_slow: Callable
    smooth_wheel_backend_factory: Optional[Callable] = None


def create_davinci_wheel_manager_class(runtime):
    """Create the singleton manager against one explicit runtime boundary."""
    config = runtime.config

    class DaVinciWheelManager:
        """DaVinci Color Wheels interaction manager."""

        _instance: Optional['DaVinciWheelManager'] = None

        def __new__(cls):
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

        def __init__(self):
            if self._initialized:
                return
            self._initialized = True
            initialize_manager_fields(self)
            self._reset_visual_feedback = WheelResetVisualFeedback(
                self, qt=runtime.pyqt_available,
            )
            mouse = runtime.platform_mouse_input
            actions = runtime.platform_mouse_actions
            detection = runtime.wheel_detection_adapter
            self._release_bindings = ManagerReleaseBindings(
                self,
                mouse_drag_end_fn=actions.mouse_drag_end,
                get_cursor_position_fn=mouse.get_cursor_position,
                set_cursor_position_fn=mouse.set_cursor_position,
                debug_slow_fn=runtime.debug_slow,
            )
            self._handle_detection_bindings = ManagerHandleDetectionBindings(
                self,
                detect_wheel_circle_in_area_fn=detection.detect_wheel_circle_in_area,
                detect_handle_in_area_fn=detection.detect_handle_in_area,
                is_ready_for_interaction_fn=partial(
                    is_davinci_ready_for_interaction,
                    self,
                ),
                clear_hover_state_fn=self._clear_hover_state,
                davinci_running_fn=lambda: self._davinci_running,
                debug_slow_fn=runtime.debug_slow,
            )
            self._wheel_motion_bindings = ManagerWheelMotionBindings(
                self,
                detect_wheel_circle_in_area_fn=detection.detect_wheel_circle_in_area,
                detect_handle_fn=self.detect_handle,
                detect_raw_handle_fn=self._detect_handle_raw_for_area,
                mouse_drag_begin_fn=actions.mouse_drag_begin,
                mouse_drag_move_by_path_fn=actions.mouse_drag_move_by_path,
                mouse_drag_move_path_fn=actions.mouse_drag_move_path,
                mouse_drag_move_absolute_path_fn=actions.mouse_drag_move_absolute_path,
                mouse_drag_end_fn=actions.mouse_drag_end,
                get_cursor_position_fn=mouse.get_cursor_position,
                clear_wheel_orbit_fn=self._clear_wheel_orbit,
                release_param_drag_fn=self._release_param_drag,
                release_wheel_drag_fn=self._release_wheel_drag,
                release_wheel_orbit_drag_fn=self._release_wheel_orbit_drag,
                note_wheel_dial_activity_fn=self.note_wheel_dial_activity,
                refresh_wheel_overlay_state_fn=partial(
                    refresh_wheel_overlay_state,
                    self,
                ),
                clear_wheel_anchor_state_fn=partial(clear_wheel_anchor_state, self),
                set_cursor_position_fn=mouse.set_cursor_position,
                pump_win32_messages_fn=(
                    runtime.pump_win32_messages
                    if runtime.win32_overlay_available
                    else None
                ),
                debug_slow_fn=runtime.debug_slow,
            )
            self._wheel_reset_bindings = ManagerWheelResetBindings(
                self,
                detect_wheel_circle_in_area_fn=detection.detect_wheel_circle_in_area,
                detect_handle_fn=self.detect_handle,
                mouse_click_fn=actions.mouse_click,
                mouse_drag_begin_fn=actions.mouse_drag_begin,
                mouse_drag_move_path_fn=actions.mouse_drag_move_path,
                mouse_drag_end_fn=actions.mouse_drag_end,
                get_cursor_position_fn=mouse.get_cursor_position,
                release_param_drag_fn=self._release_param_drag,
                release_wheel_drag_fn=self._release_wheel_drag,
                is_ready_for_interaction_fn=partial(
                    is_davinci_ready_for_interaction,
                    self,
                ),
                clear_hover_state_fn=self._clear_hover_state,
                davinci_running_fn=lambda: self._davinci_running,
                set_cursor_position_fn=mouse.set_cursor_position,
            )
            if runtime.smooth_wheel_backend_factory is not None:
                try:
                    self._smooth_wheel_backend = (
                        runtime.smooth_wheel_backend_factory(self)
                    )
                except Exception as exc:
                    self._smooth_wheel_backend = None
                    runtime.debug_slow(
                        f"smooth wheel backend initialization failed: {exc}"
                    )

        def is_ready(self):
            return bool(self.label_finder and self.areas)

        def note_param_dial_activity(self):
            return manager_note_param_dial_activity(
                self,
                lock_seconds=config.param_dial_hover_lock_seconds,
            )

        def note_wheel_dial_activity(self, area=None):
            return manager_note_wheel_dial_activity(
                self,
                area,
                lock_seconds=config.wheel_dial_hover_lock_seconds,
                debug_slow_fn=runtime.debug_slow,
            )

        def _schedule_param_release_timer(self, delay=None):
            return self._release_bindings.schedule_param_release_timer(delay=delay)

        def _release_param_drag(self, restore_cursor=True):
            return self._release_bindings.release_param_drag(
                restore_cursor=restore_cursor,
            )

        def _release_wheel_drag(self):
            return self._release_bindings.release_wheel_drag()

        def _release_wheel_orbit_drag(self, restore_cursor=True):
            return self._release_bindings.release_wheel_orbit_drag(
                restore_cursor=restore_cursor,
            )

        def _clear_wheel_orbit(self):
            return self._release_bindings.clear_wheel_orbit()

        def _release_param_drag_after_idle(self):
            return self._release_bindings.release_param_drag_after_idle()

        def _release_param_drag_if_idle(self):
            return self._release_bindings.release_param_drag_if_idle()

        def _release_wheel_drag_if_idle(self):
            return self._release_bindings.release_wheel_drag_if_idle()

        def _release_wheel_orbit_if_idle(self):
            return self._release_bindings.release_wheel_orbit_if_idle()

        def _release_param_drag_if_cursor_moved(self, mouse_x, mouse_y):
            return self._release_bindings.release_param_drag_if_cursor_moved(
                mouse_x,
                mouse_y,
            )

        def _release_wheel_orbit_if_cursor_moved(self, mouse_x, mouse_y):
            return self._release_bindings.release_wheel_orbit_if_cursor_moved(
                mouse_x,
                mouse_y,
            )

        def _move_param_drag(self, ticks):
            actions = runtime.platform_mouse_actions
            return move_param_drag(
                self,
                ticks,
                actions.mouse_drag_move_by,
                actions.mouse_drag_move,
                note_param_dial_activity_fn=self.note_param_dial_activity,
                schedule_param_release_timer_fn=self._schedule_param_release_timer,
            )

        def _handle_param_dial_drag(self, area, ticks):
            mouse = runtime.platform_mouse_input
            actions = runtime.platform_mouse_actions
            return handle_param_dial_drag(
                self,
                area,
                ticks,
                mouse.get_cursor_position,
                actions.mouse_drag_begin,
                actions.mouse_drag_move_by,
                actions.mouse_drag_move,
                runtime.wheel_detection_adapter.detect_vertical_slider_handle,
                self._release_param_drag,
                partial(
                    lock_hover_for_param_dial,
                    self,
                    lock_seconds=config.param_dial_hover_lock_seconds,
                ),
                self.note_param_dial_activity,
                self._schedule_param_release_timer,
                debug_slow_fn=runtime.debug_slow,
            )

        def initialize(self) -> tuple:
            result = initialize_manager(
                self,
                davinci_available=runtime.davinci_available,
                davinci_dependency_message=runtime.davinci_dependency_message,
                overlay_available=runtime.overlay_available,
                is_mac=runtime.is_mac,
                is_screen_locked_fn=(
                    runtime.is_mac_screen_locked if runtime.is_mac else None
                ),
                ax_is_process_trusted_fn=(
                    runtime.ax_is_process_trusted
                    if runtime.is_mac and runtime.davinci_available
                    else None
                ),
                qapplication_cls=runtime.qapplication_cls,
                argv=runtime.argv,
                label_finder_factory=runtime.label_finder_factory,
                sync_wheel_overlays_fn=sync_wheel_overlays,
            )
            if result[0]:
                self.resume_smooth_wheel('manager_cleanup')
            return result

        def start_monitoring(self, on_hover_callback=None):
            """Start mouse and DaVinci state monitoring."""
            result = start_manager_monitoring(
                self,
                on_hover_callback=on_hover_callback,
                monitor_thread_factory=runtime.monitor_thread_factory,
                pyqt_available=runtime.pyqt_available,
                timer_factory=runtime.qtimer_cls,
                left_button_immediate_callback=self._on_left_button_change_immediate,
                check_hover_fn=self._check_hover,
                left_button_change_fn=self._on_left_button_change,
                davinci_state_change_fn=self._on_davinci_state_change,
                scheduled_layout_refresh_fn=self._process_scheduled_layout_refresh,
                debug_slow_fn=runtime.debug_slow,
                diagnostics_enabled=config.debug_slow_log_enabled,
                diagnostics_message=(
                    "diagnostics enabled "
                    f"hover_poll={config.hover_poll_interval_ms}ms "
                    f"state_check={config.davinci_state_check_interval_ms}ms "
                    "area_refresh=on-demand "
                    f"min={config.area_refresh_interval_seconds:.1f}s "
                    f"mouse_idle={config.area_refresh_mouse_idle_seconds:.2f}s "
                    f"fallback={config.area_refresh_idle_fallback_seconds:.1f}s "
                    "layout_refresh_guard=smooth.11-layout.1 "
                    "diameter_continuity=smooth.11-axis.1 "
                    "axis_trace=smooth.11-axis.1-trace.3 "
                    "center_continuity=smooth.11-axis.1-center.1 "
                    "axis_rearm=smooth.11-axis.1-center.2 "
                    "confirmed_geometry=smooth.11-geometry.1 "
                    "push_pull_acceleration=smooth.11-pushaccel.4 "
                    "orbit_acceleration=orbitaccel.7 "
                    "button_poll=buttonpoll.1 "
                    "orbit_recovery=orbitrecover.3 rim_handle=rimhandle.1 transport_trace=transporttrace.1 rebase_fix=rebasefix.1 rebase_cursor=rebasecursor.1 rebase_control=normal.100 edge_margin=100 cadence_trace=cadencetrace.1 orbit_continuity=orbitflow.1 orbit_pacing=orbitpace.2 axis_alignment=axisalign.1 "
                    "reset_visual=smooth.11-resetvisual.1 "
                    "numeric_trace=same-frame-YRGB-and-wheel-archive"
                ),
            )
            if self.is_monitoring:
                self.resume_smooth_wheel('monitoring_stopped')
            return result

        def stop_monitoring(self):
            """Stop monitoring and release active interactions."""
            self.suspend_smooth_wheel('monitoring_stopped')
            return stop_manager_monitoring(
                self,
                clear_wheel_orbit_fn=self._clear_wheel_orbit,
                release_param_drag_fn=self._release_param_drag,
                release_wheel_drag_fn=self._release_wheel_drag,
            )

        def _process_scheduled_layout_refresh(self):
            can_refresh_layout_fn = partial(
                can_refresh_layout,
                self,
                left_mouse_button_down_fn=runtime.is_left_mouse_button_down,
                plugin_mouse_button_active_fn=runtime.plugin_mouse_button_state.active,
                param_refresh_grace_seconds=(
                    config.param_dial_refresh_grace_seconds
                ),
                wheel_refresh_grace_seconds=(
                    config.wheel_dial_refresh_grace_seconds
                ),
            )
            layout_refresh_due_fn = partial(
                layout_refresh_due,
                self,
                can_refresh_layout_fn=can_refresh_layout_fn,
                interval_seconds=config.area_refresh_interval_seconds,
                mouse_idle_seconds=config.area_refresh_mouse_idle_seconds,
                mouse_move_max_age_seconds=(
                    config.area_refresh_mouse_move_max_age_seconds
                ),
                force_min_interval_seconds=(
                    config.area_refresh_force_min_interval_seconds
                ),
                idle_fallback_seconds=config.area_refresh_idle_fallback_seconds,
            )
            return process_scheduled_layout_refresh(
                self,
                layout_refresh_due_fn=layout_refresh_due_fn,
                update_state_fn=self._update_state,
                debug_slow_fn=runtime.debug_slow,
                debug_update_state_ms=config.debug_update_state_ms,
                wheel_refresh_grace_seconds=config.wheel_dial_refresh_grace_seconds,
            )

        def process_events(self):
            """Process UI events and refresh non-Qt backends."""
            self._reset_visual_feedback.pump()
            smooth_result = None
            if self._smooth_wheel_backend is not None:
                smooth_result = self._smooth_wheel_backend.process_events()
            result = process_manager_events(
                self,
                pyqt_available=runtime.pyqt_available,
                win32_overlay_available=runtime.win32_overlay_available,
                pump_win32_messages_fn=runtime.pump_win32_messages,
                process_overlay_events_fn=runtime.process_overlay_events,
                release_param_if_idle_fn=self._release_param_drag_if_idle,
                release_wheel_if_idle_fn=self._release_wheel_drag_if_idle,
                release_orbit_if_idle_fn=self._release_wheel_orbit_if_idle,
                scheduled_layout_refresh_fn=self._process_scheduled_layout_refresh,
            )
            if smooth_result and smooth_result.get('ended'):
                mouse_x, mouse_y = runtime.platform_mouse_input.get_cursor_position()
                self._check_hover(mouse_x, mouse_y)
            return result

        def _clear_hover_state(self, clear_areas=False):
            token = object()
            self.suspend_smooth_wheel('hover_cleared', token=token)
            try:
                return clear_hover_state(
                    self,
                    clear_areas=clear_areas,
                    clear_wheel_orbit_fn=self._clear_wheel_orbit,
                    release_param_drag_fn=self._release_param_drag,
                    release_wheel_drag_fn=self._release_wheel_drag,
                )
            finally:
                self.resume_smooth_wheel('hover_cleared', token=token)

        def _begin_manual_wheel_drag(self, area, mouse_x, mouse_y):
            return begin_manual_wheel_drag(
                self,
                area,
                mouse_x,
                mouse_y,
                overlay_class=runtime.overlay_factory,
                clear_wheel_orbit_fn=self._clear_wheel_orbit,
                release_param_drag_fn=self._release_param_drag,
                release_wheel_drag_fn=self._release_wheel_drag,
                state_callbacks=wheel_manual_drag_state_callbacks(self),
                debug_slow_fn=runtime.debug_slow,
            )

        def _on_left_button_change_immediate(self, is_down, mouse_x, mouse_y):
            return begin_manual_wheel_drag_immediate(
                self,
                is_down,
                mouse_x,
                mouse_y,
                plugin_mouse_button_active_fn=runtime.plugin_mouse_button_state.active,
                native_overlay_enabled=(
                    runtime.is_windows
                    and runtime.win32_available
                    and runtime.overlay_force_win32_native
                ),
                state_callbacks=wheel_manual_drag_state_callbacks(self),
                debug_slow_fn=runtime.debug_slow,
            )

        def _end_manual_wheel_drag(self, mouse_x, mouse_y):
            return end_manual_wheel_drag(
                self,
                mouse_x,
                mouse_y,
                detect_handle_raw_for_area_fn=self._detect_handle_raw_for_area,
                state_callbacks=wheel_manual_drag_state_callbacks(self),
                debug_slow_fn=runtime.debug_slow,
            )

        def _on_left_button_change(self, is_down, mouse_x, mouse_y):
            if is_down:
                note_layout_switch_click(
                    self,
                    mouse_x,
                    mouse_y,
                    plugin_mouse_button_active_fn=(
                        runtime.plugin_mouse_button_state.active
                    ),
                    sync_wheel_overlays_fn=sync_wheel_overlays,
                    check_hover_fn=self._check_hover,
                    debug_slow_fn=runtime.debug_slow,
                )
            return handle_manual_wheel_drag_button_change(
                self,
                is_down,
                mouse_x,
                mouse_y,
                plugin_mouse_button_active_fn=runtime.plugin_mouse_button_state.active,
                ready_for_interaction_fn=partial(
                    is_davinci_ready_for_interaction,
                    self,
                ),
                begin_manual_drag_fn=self._begin_manual_wheel_drag,
                end_manual_drag_fn=self._end_manual_wheel_drag,
                state_callbacks=wheel_manual_drag_state_callbacks(self),
                debug_slow_fn=runtime.debug_slow,
            )

        def _update_state(self):
            return update_manager_state(
                self,
                is_windows=runtime.is_windows,
                get_cursor_position_fn=(
                    runtime.platform_mouse_input.get_cursor_position
                ),
                sync_wheel_overlays_fn=sync_wheel_overlays,
                clear_hover_state_fn=self._clear_hover_state,
                check_hover_fn=self._check_hover,
                debug_slow_fn=runtime.debug_slow,
                debug_state_check_ms=config.debug_state_check_ms,
                debug_update_state_ms=config.debug_update_state_ms,
            )

        def _check_hover(self, mouse_x, mouse_y):
            smooth_backend = self._smooth_wheel_backend
            if smooth_backend is not None and smooth_backend.is_active():
                smooth_area = smooth_backend.active_area
                if smooth_area is not None:
                    # The TourBox-style transport intentionally leaves the
                    # visible cursor at a roomy proxy point. Keep the formal
                    # target stable until its event tap observes real user
                    # input and cancels the session.
                    self.current_hover_area = smooth_area
                    return
            show_hover_overlay_fn = partial(
                show_hover_overlay_for_manager,
                self,
                overlay_factory=runtime.overlay_factory,
                detect_handle_raw_for_area_fn=self._detect_handle_raw_for_area,
                debug_slow_fn=runtime.debug_slow,
            )
            return check_hover(
                self,
                mouse_x,
                mouse_y,
                plugin_mouse_button_active_fn=runtime.plugin_mouse_button_state.active,
                left_mouse_button_down_fn=runtime.is_left_mouse_button_down,
                min_mouse_move_distance_px=(
                    config.area_refresh_mouse_move_min_distance_px
                ),
                is_ready_for_interaction_fn=partial(
                    is_davinci_ready_for_interaction,
                    self,
                ),
                clear_hover_state_fn=self._clear_hover_state,
                release_param_if_cursor_moved_fn=(
                    self._release_param_drag_if_cursor_moved
                ),
                release_wheel_drag_fn=self._release_wheel_drag,
                clear_wheel_orbit_fn=self._clear_wheel_orbit,
                ensure_locked_hover_overlay_visible_fn=partial(
                    ensure_locked_hover_overlay_visible,
                    self,
                    show_hover_overlay_fn=show_hover_overlay_fn,
                ),
                release_wheel_drag_if_idle_fn=self._release_wheel_drag_if_idle,
                release_wheel_orbit_if_cursor_moved_fn=(
                    self._release_wheel_orbit_if_cursor_moved
                ),
                show_hover_overlay_fn=show_hover_overlay_fn,
                on_hover_change_fn=(
                    lambda hover_label: self._on_hover_callback(hover_label)
                    if self._on_hover_callback
                    else None
                ),
                debug_slow_fn=runtime.debug_slow,
                debug_callback_process_ms=config.debug_callback_process_ms,
            )

        def _on_davinci_state_change(self, is_active):
            return handle_davinci_state_change(
                self,
                is_active,
                clear_hover_state_fn=self._clear_hover_state,
                request_layout_refresh_fn=partial(request_layout_refresh, self),
            )

        def detect_handle(self, area_name):
            return self._handle_detection_bindings.detect_handle(area_name)

        def _detect_handle_raw_for_area(
            self,
            area,
            expected_handle=None,
            expected_axis=None,
        ):
            return self._handle_detection_bindings.detect_raw_for_area(
                area,
                expected_handle=expected_handle,
                expected_axis=expected_axis,
            )

        def run_tourbox_offscreen_probe(
            self,
            ticks=1,
            mode='offscreen',
            wheel_name='Offset',
        ):
            from ..diagnostics.tourbox_probe_runner import (
                run_tourbox_offscreen_probe_action,
            )

            mouse = runtime.platform_mouse_input
            return run_tourbox_offscreen_probe_action(
                self,
                ticks=ticks,
                mode=mode,
                wheel_name=wheel_name,
                win32_input_available=(
                    runtime.is_windows and runtime.win32_available
                ),
                detect_wheel_circle_in_area_fn=(
                    runtime.wheel_detection_adapter.detect_wheel_circle_in_area
                ),
                get_cursor_position_fn=mouse.get_cursor_position,
                point_in_screen_bounds_fn=mouse.point_in_screen_bounds,
                set_cursor_position_fn=mouse.set_cursor_position,
                send_absolute_move_fn=mouse.send_absolute_move,
                send_relative_move_fn=mouse.send_relative_move,
                send_left_down_fn=mouse.send_left_down,
                send_left_up_fn=mouse.send_left_up,
                recent_wheel_area_fn=lambda: recent_wheel_area(self),
                release_param_drag_fn=self._release_param_drag,
                release_wheel_drag_fn=self._release_wheel_drag,
                release_wheel_orbit_drag_fn=self._release_wheel_orbit_drag,
                detect_raw_handle_fn=self._detect_handle_raw_for_area,
            )

        def run_tourbox_orbit_probe(
            self,
            ticks=1,
            mode='local_arc',
            wheel_name='Offset',
        ):
            from ..diagnostics.tourbox_probe_runner import (
                run_tourbox_orbit_probe_action,
            )

            mouse = runtime.platform_mouse_input
            return run_tourbox_orbit_probe_action(
                self,
                ticks=ticks,
                mode=mode,
                wheel_name=wheel_name,
                win32_input_available=(
                    runtime.is_windows and runtime.win32_available
                ),
                detect_wheel_circle_in_area_fn=(
                    runtime.wheel_detection_adapter.detect_wheel_circle_in_area
                ),
                get_cursor_position_fn=mouse.get_cursor_position,
                point_in_screen_bounds_fn=mouse.point_in_screen_bounds,
                set_cursor_position_fn=mouse.set_cursor_position,
                send_absolute_move_fn=mouse.send_absolute_move,
                send_left_down_fn=mouse.send_left_down,
                send_left_up_fn=mouse.send_left_up,
                recent_wheel_area_fn=lambda: recent_wheel_area(self),
                release_param_drag_fn=self._release_param_drag,
                release_wheel_drag_fn=self._release_wheel_drag,
                release_wheel_orbit_drag_fn=self._release_wheel_orbit_drag,
                detect_raw_handle_fn=self._detect_handle_raw_for_area,
            )

        def _handle_wheel_dial_rotate_closed(self, area, ticks):
            return self._wheel_motion_bindings.handle_closed(area, ticks)

        def _handle_wheel_orbit_closed_loop(self, area, ticks):
            return self._wheel_motion_bindings.handle_orbit_closed_loop(area, ticks)

        def _handle_wheel_outer_anchor_rotate(self, area, ticks):
            return self._wheel_motion_bindings.handle_outer_anchor_rotate(area, ticks)

        def _handle_wheel_dial_rotate_segment(self, area, ticks):
            return self._wheel_motion_bindings.handle_segment(area, ticks)

        def _handle_wheel_diameter_rotate(self, area, ticks):
            return self._wheel_motion_bindings.handle_diameter_rotate(area, ticks)

        def _handle_wheel_dial_rotate(self, area, ticks, is_hold):
            return self._wheel_motion_bindings.handle_dial_rotate(area, ticks, is_hold)

        def _run_wheel_reset_transaction(self, reset_action, area=None):
            def reset_transaction():
                if not retire_smooth_before_legacy(
                    self._smooth_wheel_backend,
                    'wheel_reset',
                ):
                    return False
                return reset_action()

            def run_transaction():
                backend = self._smooth_wheel_backend
                transaction = getattr(backend, 'run_smooth_transaction', None)
                if callable(transaction):
                    return transaction(reset_transaction)
                return reset_transaction()

            if area is None:
                area = self.current_hover_area
                if not area or area.get('type') != 'wheel':
                    drag = wheel_drag_state(self)
                    area = drag.get('area') if drag else None
            feedback = getattr(self, '_reset_visual_feedback', None)
            if feedback is not None:
                # Wait for the UI preview only BEFORE taking the lifecycle
                # lock; the UI loop polls the same lock after pumping feedback.
                return feedback.run(area, run_transaction)
            return run_transaction()

        def _reset_wheel_via_native_button(self, area) -> bool:
            return self._run_wheel_reset_transaction(
                lambda: self._wheel_reset_bindings.reset_via_native_button(area), area,
            )

        def reset_current_wheel_to_center(self) -> bool:
            return self._run_wheel_reset_transaction(
                self._wheel_reset_bindings.reset_current_wheel_to_center,
            )

        def try_submit_smooth_dial(
            self,
            ticks,
            *,
            is_hold=False,
            mode=None,
            action_context=None,
            wheel_settings_explicit=False,
        ):
            def submit_smooth():
                return try_handle_manager_smooth_wheel_dial(
                    self,
                    ticks,
                    is_hold=is_hold,
                    mode=mode,
                    action_context=action_context,
                    wheel_settings_explicit=wheel_settings_explicit,
                    smooth_backend=self._smooth_wheel_backend,
                    active_wheel_target_area_fn=active_wheel_target_area,
                    wheel_drag_state_fn=wheel_drag_state,
                    wheel_orbit_state_fn=wheel_orbit_state,
                    clear_wheel_control_state_fn=clear_wheel_control_state,
                    is_ready_for_interaction_fn=partial(
                        is_davinci_ready_for_interaction,
                        self,
                    ),
                    active_locked_hover_area_fn=partial(
                        active_locked_hover_area,
                        self,
                    ),
                    note_wheel_dial_activity_fn=self.note_wheel_dial_activity,
                    sensitivity=self.sensitivity,
                    debug_slow_fn=runtime.debug_slow,
                )

            backend = self._smooth_wheel_backend
            transaction = getattr(backend, 'run_smooth_transaction', None)
            if callable(transaction):
                return transaction(submit_smooth)
            return submit_smooth()

        def cancel_smooth_wheel(self, reason='cancel'):
            if self._smooth_wheel_backend is None:
                return True
            return self._smooth_wheel_backend.cancel(reason)

        def suspend_smooth_wheel(self, reason='suspended', *, token=None):
            if self._smooth_wheel_backend is None:
                return True
            suspend = getattr(self._smooth_wheel_backend, 'suspend', None)
            if callable(suspend):
                if token is None:
                    return suspend(reason)
                return suspend(reason, token=token)
            return self._smooth_wheel_backend.cancel(reason)

        def resume_smooth_wheel(self, reason='suspended', *, token=None):
            if self._smooth_wheel_backend is None:
                return True
            resume = getattr(self._smooth_wheel_backend, 'resume', None)
            if callable(resume):
                if token is None:
                    return resume(reason)
                return resume(reason, token=token)
            return True

        def smooth_wheel_status(self):
            if self._smooth_wheel_backend is None:
                return {
                    'available': False,
                    'active': False,
                    'runtimeVersion': None,
                }
            return self._smooth_wheel_backend.snapshot()

        def handle_dial_rotate(
            self,
            ticks: int,
            is_hold: bool = False,
            mode: str = None,
            action_context: str = None,
            wheel_settings_explicit: bool = False,
        ) -> bool:
            def dispatch_legacy():
                return handle_manager_dial_rotate(
                    self,
                    ticks,
                    is_hold=is_hold,
                    mode=mode,
                    action_context=action_context,
                    wheel_settings_explicit=wheel_settings_explicit,
                    param_dial_area_types={'numeric', 'slider', 'vertical_slider'},
                    active_wheel_target_area_fn=active_wheel_target_area,
                    wheel_drag_state_fn=wheel_drag_state,
                    wheel_orbit_state_fn=wheel_orbit_state,
                    clear_wheel_control_state_fn=clear_wheel_control_state,
                    is_ready_for_interaction_fn=partial(
                        is_davinci_ready_for_interaction,
                        self,
                    ),
                    clear_hover_state_fn=self._clear_hover_state,
                    move_param_drag_fn=self._move_param_drag,
                    active_locked_hover_area_fn=partial(active_locked_hover_area, self),
                    handle_wheel_dial_rotate_fn=self._handle_wheel_dial_rotate,
                    clear_wheel_orbit_fn=self._clear_wheel_orbit,
                    release_wheel_drag_fn=self._release_wheel_drag,
                    release_param_drag_fn=self._release_param_drag,
                    handle_param_dial_drag_fn=self._handle_param_dial_drag,
                    debug_slow_fn=runtime.debug_slow,
                )

            backend = self._smooth_wheel_backend
            run_legacy = getattr(backend, 'run_legacy_if_idle', None)
            if callable(run_legacy):
                return run_legacy(dispatch_legacy)
            return dispatch_legacy()

        def set_sensitivity(self, sensitivity: float):
            self.sensitivity = max(0.1, min(10.0, sensitivity))

        def get_current_area(self):
            return self.current_hover_area

        def cleanup(self):
            self.suspend_smooth_wheel('manager_cleanup')
            return cleanup_manager(
                self,
                clear_wheel_control_state_fn=clear_wheel_control_state,
                clear_wheel_handles_fn=clear_wheel_handles,
                clear_wheel_orbit_fn=self._clear_wheel_orbit,
                release_param_drag_fn=self._release_param_drag,
                release_wheel_drag_fn=self._release_wheel_drag,
                stop_monitoring_fn=self.stop_monitoring,
            )

    return DaVinciWheelManager


__all__ = [
    'DaVinciManagerRuntime',
    'create_davinci_wheel_manager_class',
]
