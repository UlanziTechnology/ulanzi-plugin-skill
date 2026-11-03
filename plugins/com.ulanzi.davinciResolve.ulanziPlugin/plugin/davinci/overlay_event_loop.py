"""Overlay event-loop helpers."""


def process_overlay_events_cycle(
    callbacks,
    callbacks_lock,
    tk_root,
    *,
    time_module,
    tkinter_available,
    tk_error_cls,
    win32_overlay_available,
    pump_win32_messages_fn,
    debug_slow_fn,
    debug_callback_latency_ms,
    debug_callback_process_ms,
    debug_tk_update_ms,
):
    started_at = time_module.perf_counter()
    with callbacks_lock:
        pending = list(callbacks.values())
        callbacks.clear()

    callback_started_at = time_module.perf_counter()
    max_latency_ms = 0.0
    for item in pending:
        if len(item) == 4:
            callback, args, kwargs, queued_at = item
            max_latency_ms = max(max_latency_ms, (callback_started_at - queued_at) * 1000.0)
        else:
            callback, args, kwargs = item
        try:
            callback(*args, **kwargs)
        except Exception as e:
            print(f"main thread callback failed: {e}")
    callback_ms = (time_module.perf_counter() - callback_started_at) * 1000.0

    if pending and max_latency_ms >= debug_callback_latency_ms:
        debug_slow_fn(f"main callback latency {max_latency_ms:.1f}ms pending={len(pending)}")
    if pending and callback_ms >= debug_callback_process_ms:
        debug_slow_fn(f"main callback processing {callback_ms:.1f}ms pending={len(pending)}")

    if tkinter_available and tk_root is not None:
        tk_started_at = time_module.perf_counter()
        try:
            tk_root.update_idletasks()
            tk_root.update()
        except tk_error_cls:
            pass
        tk_ms = (time_module.perf_counter() - tk_started_at) * 1000.0
        if tk_ms >= debug_tk_update_ms:
            debug_slow_fn(f"tk update {tk_ms:.1f}ms pending={len(pending)}")

    if win32_overlay_available:
        pump_win32_messages_fn()

    total_ms = (time_module.perf_counter() - started_at) * 1000.0
    if pending and total_ms >= debug_callback_process_ms:
        debug_slow_fn(f"overlay event cycle {total_ms:.1f}ms pending={len(pending)}")


__all__ = ['process_overlay_events_cycle']
