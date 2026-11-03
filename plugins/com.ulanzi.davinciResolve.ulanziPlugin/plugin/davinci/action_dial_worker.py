"""Dial worker loop and tail-release helpers for DaVinci wheel actions."""


def enqueue_dial_event(
    action,
    ticks,
    *,
    is_hold,
    wheel_manager,
    time_fn,
    thread_factory,
    dial_queue_max_pending,
    continuous_param_drag_types,
    wheel_drag_state_fn,
    wheel_orbit_state_fn,
    recent_wheel_area_fn,
):
    if ticks == 0:
        return False

    with action._dial_condition:
        now = time_fn()
        mode = wheel_mode_for_event(
            action,
            is_hold,
            wheel_manager=wheel_manager,
            wheel_drag_state_fn=wheel_drag_state_fn,
            recent_wheel_area_fn=recent_wheel_area_fn,
        )
        current_area = wheel_manager.get_current_area()
        current_area_type = current_area.get('type') if current_area else None
        if (
            current_area_type in continuous_param_drag_types
            or (
                wheel_manager._param_drag
                and wheel_manager._param_drag.get('target_type') in continuous_param_drag_types
            )
        ):
            wheel_manager.note_param_dial_activity()
        if (
            current_area_type == 'wheel'
            or wheel_drag_state_fn(wheel_manager)
            or wheel_orbit_state_fn(wheel_manager)
            or recent_wheel_area_fn(wheel_manager)
        ):
            wheel_manager.note_wheel_dial_activity(
                current_area if current_area_type == 'wheel' else None
            )
        event = {
            'ticks': ticks,
            'is_hold': is_hold,
            'mode': mode,
            'action_context': action.context,
            'wheel_settings_explicit': bool(
                getattr(action, 'wheel_settings_explicit', False)
            ),
            'queued_at': now,
            'generation': getattr(action, '_dial_generation', 0),
        }
        if (
            action._pending_dial
            and action._pending_dial[-1]['is_hold'] == is_hold
            and action._pending_dial[-1].get('mode') == mode
            and action._pending_dial[-1].get('generation') == event.get('generation')
        ):
            action._pending_dial[-1]['ticks'] += ticks
            action._pending_dial[-1]['queued_at'] = now
        else:
            action._pending_dial.append(event)
        action._last_dial_enqueue_at = now

        # Old wheel ticks are visual history; do not replay a long backlog.
        if len(action._pending_dial) > dial_queue_max_pending:
            action._pending_dial = action._pending_dial[-dial_queue_max_pending:]

        action._dial_worker_stop = False
        if not action._dial_worker or not action._dial_worker.is_alive():
            action._dial_worker = thread_factory(
                target=action._dial_worker_loop,
                daemon=True,
            )
            action._dial_worker.start()

        action._dial_condition.notify()
    return True


def wheel_mode_for_event(
    action,
    is_hold,
    *,
    wheel_manager,
    wheel_drag_state_fn,
    recent_wheel_area_fn,
):
    area = wheel_manager.get_current_area()
    area_type = area.get('type') if area else None
    if area_type == 'wheel' or wheel_drag_state_fn(wheel_manager) or recent_wheel_area_fn(wheel_manager):
        return action.hold_dial_mode if is_hold else action.dial_mode
    return None


def wait_for_param_dial_tail(
    action,
    *,
    wheel_manager,
    time_fn,
    release_param_drag_after_idle_fn,
    get_cursor_position_fn,
    mouse_drag_end_fn,
    set_cursor_position_fn,
    debug_slow_fn,
    queue_tail_release_seconds,
):
    if not wheel_manager._param_drag:
        return False

    with action._dial_condition:
        deadline = time_fn() + queue_tail_release_seconds
        while (
            not action._pending_dial
            and not action._dial_worker_stop
        ):
            remaining = deadline - time_fn()
            if remaining <= 0:
                break
            action._dial_condition.wait(timeout=remaining)

        has_more = bool(action._pending_dial) and not action._dial_worker_stop

    if has_more:
        return True

    if wheel_manager._param_drag:
        debug_slow_fn("param drag tail release")
        release_param_drag_after_idle_fn(
            wheel_manager,
            get_cursor_position_fn,
            mouse_drag_end_fn,
            set_cursor_position_fn=set_cursor_position_fn,
            debug_slow_fn=debug_slow_fn,
        )
    return False


def take_pending_dial(
    action,
    *,
    time_fn,
    debug_slow_fn,
    dial_queue_idle_discard_seconds,
):
    with action._dial_condition:
        if action._dial_worker_stop:
            action._pending_dial.clear()
            action._dial_worker = None
            return None

        if not action._pending_dial:
            action._dial_worker = None
            return None

        idle_seconds = time_fn() - action._last_dial_enqueue_at
        if idle_seconds >= dial_queue_idle_discard_seconds:
            pending_count = len(action._pending_dial)
            action._pending_dial.clear()
            action._dial_worker = None
            debug_slow_fn(
                "dial queue discarded stale pending="
                f"{pending_count} idle={idle_seconds * 1000:.0f}ms"
            )
            return None

        return action._pending_dial.pop(0)


def discard_dial_backlog_if_idle(
    action,
    reason,
    *,
    time_fn,
    debug_slow_fn,
    dial_queue_idle_discard_seconds,
):
    with action._dial_condition:
        if not action._last_dial_enqueue_at:
            return False
        idle_seconds = time_fn() - action._last_dial_enqueue_at
        if idle_seconds < dial_queue_idle_discard_seconds:
            return False
        pending_count = len(action._pending_dial)
        action._pending_dial.clear()

    debug_slow_fn(
        "dial queue idle stop "
        f"reason={reason} pending={pending_count} idle={idle_seconds * 1000:.0f}ms"
    )
    return True


def coalesce_param_dial_event(
    action,
    event,
    *,
    wheel_manager,
    time_module,
    continuous_param_drag_types,
    param_dial_fast_coalesce_seconds,
):
    area = wheel_manager.get_current_area()
    if event.get('is_hold') or not area or area.get('type') not in continuous_param_drag_types:
        return event

    time_module.sleep(param_dial_fast_coalesce_seconds)

    with action._dial_condition:
        while (
            action._pending_dial
            and action._pending_dial[0]['is_hold'] == event['is_hold']
            and action._pending_dial[0].get('mode') == event.get('mode')
            and action._pending_dial[0].get('generation') == event.get('generation')
        ):
            next_event = action._pending_dial.pop(0)
            event['ticks'] += next_event['ticks']
            event['queued_at'] = next_event.get('queued_at', event.get('queued_at'))
    return event


def clear_pending_dial(action):
    with action._dial_condition:
        action._dial_generation = getattr(action, '_dial_generation', 0) + 1
        action._pending_dial.clear()
        action._dial_worker_stop = True
        action._last_dial_enqueue_at = 0.0
        action._dial_condition.notify_all()


def run_dial_worker_loop(
    action,
    *,
    wheel_manager,
    dial_max_batch_ticks,
    wheel_max_ticks_per_dial_step,
):
    while True:
        event = action._take_pending_dial()
        if event is None:
            return
        event = action._coalesce_param_dial_event(event)

        with action._dial_condition:
            if (
                event.get('generation') != getattr(action, '_dial_generation', 0)
                or action._dial_worker_stop
            ):
                continue

        ticks = event['ticks']
        if ticks == 0:
            continue
        if abs(ticks) > dial_max_batch_ticks:
            ticks = dial_max_batch_ticks if ticks > 0 else -dial_max_batch_ticks

        try:
            mode = event.get('mode')
            if mode in {'orbit', 'diameter'} and abs(ticks) > wheel_max_ticks_per_dial_step:
                direction = 1 if ticks > 0 else -1
                remaining = abs(ticks)
                while remaining > 0:
                    with action._dial_condition:
                        if (
                            event.get('generation')
                            != getattr(action, '_dial_generation', 0)
                            or action._dial_worker_stop
                        ):
                            break
                    step_ticks = min(wheel_max_ticks_per_dial_step, remaining) * direction
                    wheel_manager.handle_dial_rotate(
                        step_ticks,
                        is_hold=event['is_hold'],
                        mode=mode,
                        action_context=event.get('action_context'),
                        wheel_settings_explicit=event.get(
                            'wheel_settings_explicit',
                            False,
                        ),
                    )
                    remaining -= abs(step_ticks)
                    if remaining > 0 and action._discard_dial_backlog_if_idle('split-step'):
                        break
            else:
                wheel_manager.handle_dial_rotate(
                    ticks,
                    is_hold=event['is_hold'],
                    mode=mode,
                    action_context=event.get('action_context'),
                    wheel_settings_explicit=event.get(
                        'wheel_settings_explicit',
                        False,
                    ),
                )
        except Exception as exc:
            print(f"dial handling failed: {exc}")

        if wheel_manager._param_drag and action._wait_for_param_dial_tail():
            continue


__all__ = [
    'clear_pending_dial',
    'coalesce_param_dial_event',
    'discard_dial_backlog_if_idle',
    'enqueue_dial_event',
    'run_dial_worker_loop',
    'take_pending_dial',
    'wait_for_param_dial_tail',
    'wheel_mode_for_event',
]
