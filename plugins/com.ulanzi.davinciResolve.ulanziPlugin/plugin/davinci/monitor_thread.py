"""MonitorThread factory for mouse and DaVinci active-state polling."""

import time

from .monitor_thread_loop import run_monitor_loop


def create_monitor_thread_class(
    *,
    qthread_cls,
    signal_factory,
    hover_poll_interval_ms,
    davinci_state_check_interval_ms,
    get_cursor_position_fn,
    is_left_mouse_button_down_fn,
    plugin_mouse_button_active_fn,
    debug_slow_fn,
    debug_loop_gap_ms,
    debug_state_check_ms,
):
    class MonitorThread(qthread_cls):
        """Mouse and DaVinci-window monitor thread."""

        position_changed = signal_factory(float, float)
        left_button_changed = signal_factory(bool, float, float)
        davinci_state_changed = signal_factory(bool)

        def __init__(
            self,
            label_finder,
            interval_ms=hover_poll_interval_ms,
            state_interval_ms=davinci_state_check_interval_ms,
        ):
            super().__init__()
            self.label_finder = label_finder
            self.interval_ms = interval_ms
            self.state_interval_ms = state_interval_ms
            self.running = True
            self.last_pos = None
            self.last_left_button_down = False
            self.last_davinci_active = False
            self.last_state_check = 0
            self.last_loop_at = 0
            self.left_button_immediate_callback = None

        def run(self):
            return run_monitor_loop(
                self,
                perf_counter_fn=time.perf_counter,
                time_fn=time.time,
                sleep_fn=time.sleep,
                get_cursor_position_fn=get_cursor_position_fn,
                is_left_mouse_button_down_fn=is_left_mouse_button_down_fn,
                plugin_mouse_button_active_fn=plugin_mouse_button_active_fn,
                debug_slow_fn=debug_slow_fn,
                debug_loop_gap_ms=debug_loop_gap_ms,
                debug_state_check_ms=debug_state_check_ms,
            )

        def is_davinci_active(self):
            if not self.label_finder or not self.label_finder.target_app:
                return False
            return self.label_finder.is_frontmost()

        def stop(self):
            self.running = False
            self.wait()

    MonitorThread.__name__ = 'MonitorThread'
    return MonitorThread


__all__ = ['create_monitor_thread_class']
