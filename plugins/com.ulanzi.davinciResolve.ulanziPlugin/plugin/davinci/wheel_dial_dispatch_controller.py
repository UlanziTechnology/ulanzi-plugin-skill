"""High-level dispatch for wheel dial events."""


def handle_wheel_dial_rotate(
    area,
    ticks,
    is_hold,
    *,
    outer_anchor_rotate_fn,
    diameter_rotate_fn,
    note_wheel_dial_activity_fn,
    refresh_wheel_overlay_state_fn,
    clear_wheel_anchor_state_fn,
):
    if ticks == 0:
        return False

    note_wheel_dial_activity_fn(area)

    if not is_hold:
        moved = outer_anchor_rotate_fn(area, ticks)
        refresh_wheel_overlay_state_fn(area)
        return moved

    moved = diameter_rotate_fn(area, ticks)
    refresh_wheel_overlay_state_fn(area)
    return moved


__all__ = ['handle_wheel_dial_rotate']
