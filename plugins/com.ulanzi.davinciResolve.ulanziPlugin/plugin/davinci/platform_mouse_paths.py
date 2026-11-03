"""Mouse path execution helpers shared by wheel controllers."""

import math
import time


def drag_move_path(points, move_fn, duration=0.035):
    if not points:
        return False

    delay = duration / max(1, len(points))
    moved = False
    for x, y in points:
        moved = move_fn(x, y) or moved
        time.sleep(delay)
    return moved


def drag_move_absolute_path(points, move_absolute_fn, duration=0.035):
    if not points:
        return False

    delay = duration / max(1, len(points))
    moved = False
    for x, y in points:
        moved = move_absolute_fn(x, y) or moved
        time.sleep(delay)
    return moved


def drag_move_by_vectors(vectors, move_by_fn, duration=0.035):
    if not vectors:
        return False

    delay = duration / max(1, len(vectors))
    moved = False
    for dx, dy in vectors:
        moved = move_by_fn(dx, dy) or moved
        time.sleep(delay)
    return moved


def drag_move_by_path(
    total_dx,
    total_dy,
    move_by_fn,
    *,
    steps=8,
    duration=0.035,
    max_step_px=None,
):
    steps = max(1, int(steps))
    if max_step_px and max_step_px > 0:
        distance = math.hypot(total_dx, total_dy)
        steps = max(steps, int(math.ceil(distance / max_step_px)))
    delay = duration / steps
    sent_dx = 0.0
    sent_dy = 0.0
    moved = False
    for step in range(1, steps + 1):
        target_dx = total_dx * step / steps
        target_dy = total_dy * step / steps
        dx = target_dx - sent_dx
        dy = target_dy - sent_dy
        moved = move_by_fn(dx, dy) or moved
        sent_dx = target_dx
        sent_dy = target_dy
        time.sleep(delay)
    return moved
