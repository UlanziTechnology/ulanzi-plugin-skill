"""Monitor-thread polling loop for mouse and DaVinci active-state changes."""


def run_monitor_loop(
    monitor,
    *,
    perf_counter_fn,
    time_fn,
    sleep_fn,
    get_cursor_position_fn,
    is_left_mouse_button_down_fn,
    plugin_mouse_button_active_fn,
    debug_slow_fn,
    debug_loop_gap_ms,
    debug_state_check_ms,
):
    while monitor.running:
        loop_started_at = perf_counter_fn()
        if monitor.last_loop_at:
            gap_ms = (loop_started_at - monitor.last_loop_at) * 1000.0
            expected_ms = monitor.interval_ms
            if gap_ms >= max(debug_loop_gap_ms, expected_ms * 4):
                debug_slow_fn(f"monitor loop gap {gap_ms:.1f}ms expected~{expected_ms}ms")
        monitor.last_loop_at = loop_started_at

        now = time_fn()
        cursor_started_at = perf_counter_fn()
        pos = get_cursor_position_fn()
        cursor_ms = (perf_counter_fn() - cursor_started_at) * 1000.0
        if cursor_ms >= debug_state_check_ms:
            debug_slow_fn(f"cursor position read {cursor_ms:.1f}ms pos={pos}")
        if pos != monitor.last_pos:
            monitor.last_pos = pos
            monitor.position_changed.emit(pos[0], pos[1])

        left_button_down = is_left_mouse_button_down_fn()
        if left_button_down != monitor.last_left_button_down:
            monitor.last_left_button_down = left_button_down
            debug_slow_fn(
                f"left button {'down' if left_button_down else 'up'} "
                f"pos=({pos[0]:.0f},{pos[1]:.0f}) "
                f"plugin_mouse={plugin_mouse_button_active_fn()}"
            )
            if monitor.left_button_immediate_callback:
                try:
                    monitor.left_button_immediate_callback(left_button_down, pos[0], pos[1])
                except Exception as exc:
                    debug_slow_fn(f"left button immediate callback failed: {exc}")
            monitor.left_button_changed.emit(left_button_down, pos[0], pos[1])

        if (now - monitor.last_state_check) * 1000 >= monitor.state_interval_ms:
            monitor.last_state_check = now
            state_started_at = perf_counter_fn()
            # Keep the Qt bool signal safe when a platform probe returns no app.
            is_active = bool(monitor.is_davinci_active())
            state_ms = (perf_counter_fn() - state_started_at) * 1000.0
            if state_ms >= debug_state_check_ms:
                debug_slow_fn(f"state check {state_ms:.1f}ms active={is_active}")
            if is_active != monitor.last_davinci_active:
                monitor.last_davinci_active = is_active
                monitor.davinci_state_changed.emit(is_active)

        sleep_fn(monitor.interval_ms / 1000.0)


__all__ = ['run_monitor_loop']
