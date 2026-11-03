"""Ulanzi action runtime class for DaVinci wheel control."""

from .action_dial_worker import (
    clear_pending_dial,
    coalesce_param_dial_event,
    discard_dial_backlog_if_idle,
    enqueue_dial_event,
    run_dial_worker_loop,
    take_pending_dial,
    wait_for_param_dial_tail,
)
from .action_settings import update_action_settings
from .config import (
    CONTINUOUS_PARAM_DRAG_TYPES,
    DEFAULT_SETTINGS,
    DIAL_MAX_BATCH_TICKS,
    DIAL_QUEUE_IDLE_DISCARD_SECONDS,
    DIAL_QUEUE_MAX_PENDING,
    PARAM_DIAL_FAST_COALESCE_SECONDS,
    PARAM_DIAL_QUEUE_TAIL_RELEASE_SECONDS,
    WHEEL_MAX_TICKS_PER_DIAL_STEP,
)
from .param_drag_controller import release_param_drag_after_idle
from .wheel_state_manager import (
    recent_wheel_area,
    wheel_drag_state,
    wheel_orbit_state,
)


def create_davinci_wheel_action_class(
    *,
    wheel_manager,
    threading_module,
    time_module,
    mouse_drag_end_fn,
    get_cursor_position_fn=None,
    set_cursor_position_fn=None,
    debug_slow_fn=None,
):
    if debug_slow_fn is None:
        debug_slow_fn = lambda _message: None

    class DaVinciWheelAction:
        """DaVinci Color Wheels Action."""

        def __init__(self, context: str, api):
            self.context = context
            self.ud_api = api
            self.settings = DEFAULT_SETTINGS.copy()
            self.active = False
            self.target_wheel = None
            self.dial_mode = self.settings['dial_mode']
            self.hold_dial_mode = self.settings['hold_dial_mode']
            self.wheel_settings_explicit = False
            self._dial_condition = threading_module.Condition()
            self._pending_dial = []
            self._dial_worker = None
            self._dial_worker_stop = False
            self._last_dial_enqueue_at = 0.0
            self._dial_generation = 0

        def _enqueue_dial(self, ticks: int, is_hold: bool):
            if ticks == 0:
                return False
            try_smooth = getattr(
                wheel_manager,
                'try_submit_smooth_dial',
                None,
            )
            if callable(try_smooth):
                mode = self.hold_dial_mode if is_hold else self.dial_mode
                smooth_result = try_smooth(
                    ticks,
                    is_hold=is_hold,
                    mode=mode,
                    action_context=self.context,
                    wheel_settings_explicit=bool(
                        getattr(self, 'wheel_settings_explicit', False)
                    ),
                )
                if smooth_result is not None:
                    # Invalidate a legacy event which may already have been
                    # popped by the background worker before this direct
                    # smooth takeover.  The manager also serializes the final
                    # dispatch, so no stale event can become a second owner.
                    self._clear_pending_dial()
                    return bool(smooth_result)
            return enqueue_dial_event(
                self,
                ticks,
                is_hold=is_hold,
                wheel_manager=wheel_manager,
                time_fn=time_module.time,
                thread_factory=threading_module.Thread,
                dial_queue_max_pending=DIAL_QUEUE_MAX_PENDING,
                continuous_param_drag_types=CONTINUOUS_PARAM_DRAG_TYPES,
                wheel_drag_state_fn=wheel_drag_state,
                wheel_orbit_state_fn=wheel_orbit_state,
                recent_wheel_area_fn=recent_wheel_area,
            )

        def _take_pending_dial(self):
            return take_pending_dial(
                self,
                time_fn=time_module.time,
                debug_slow_fn=debug_slow_fn,
                dial_queue_idle_discard_seconds=DIAL_QUEUE_IDLE_DISCARD_SECONDS,
            )

        def _discard_dial_backlog_if_idle(self, reason: str):
            return discard_dial_backlog_if_idle(
                self,
                reason,
                time_fn=time_module.time,
                debug_slow_fn=debug_slow_fn,
                dial_queue_idle_discard_seconds=DIAL_QUEUE_IDLE_DISCARD_SECONDS,
            )

        def _coalesce_param_dial_event(self, event):
            return coalesce_param_dial_event(
                self,
                event,
                wheel_manager=wheel_manager,
                time_module=time_module,
                continuous_param_drag_types=CONTINUOUS_PARAM_DRAG_TYPES,
                param_dial_fast_coalesce_seconds=PARAM_DIAL_FAST_COALESCE_SECONDS,
            )

        def _wait_for_param_dial_tail(self):
            return wait_for_param_dial_tail(
                self,
                wheel_manager=wheel_manager,
                time_fn=time_module.time,
                release_param_drag_after_idle_fn=release_param_drag_after_idle,
                get_cursor_position_fn=get_cursor_position_fn,
                mouse_drag_end_fn=mouse_drag_end_fn,
                set_cursor_position_fn=set_cursor_position_fn,
                debug_slow_fn=debug_slow_fn,
                queue_tail_release_seconds=PARAM_DIAL_QUEUE_TAIL_RELEASE_SECONDS,
            )

        def _dial_worker_loop(self):
            return run_dial_worker_loop(
                self,
                wheel_manager=wheel_manager,
                dial_max_batch_ticks=DIAL_MAX_BATCH_TICKS,
                wheel_max_ticks_per_dial_step=WHEEL_MAX_TICKS_PER_DIAL_STEP,
            )

        def _clear_pending_dial(self):
            return clear_pending_dial(self)

        def update_settings(self, settings: dict, action_type: str = 'init'):
            return update_action_settings(self, settings, wheel_manager=wheel_manager)

        def set_active(self, active: bool):
            self.active = active

        def on_dial_rotate(self, ticks: int):
            return self._enqueue_dial(ticks, is_hold=False)

        def on_dial_rotate_hold(self, ticks: int):
            return self._enqueue_dial(ticks, is_hold=True)

        def on_dial_down(self):
            self._clear_pending_dial()
            return wheel_manager.reset_current_wheel_to_center()

        def destroy(self):
            self._clear_pending_dial()
            if getattr(wheel_manager, '_wheel_dial_owner_context', None) == self.context:
                cancel_smooth = getattr(
                    wheel_manager,
                    'cancel_smooth_wheel',
                    None,
                )
                if callable(cancel_smooth):
                    cancel_smooth('action_destroyed')
                wheel_manager._wheel_dial_owner_context = None
                wheel_manager._wheel_dial_owner_at = 0.0
                wheel_manager._wheel_dial_owner_mode = None
            wheel_manager.action_contexts.discard(self.context)

        def on_connection_lost(self):
            self._clear_pending_dial()
            cancel_smooth = getattr(
                wheel_manager,
                'cancel_smooth_wheel',
                None,
            )
            if callable(cancel_smooth):
                cancel_smooth('connection_lost')

    return DaVinciWheelAction


__all__ = ['create_davinci_wheel_action_class']
