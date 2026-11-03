"""Raw handle detection timing for wheel diameter feedback."""

import time

from .config import (
    WHEEL_DIAMETER_CENTER_FEEDBACK_SETTLE_SECONDS,
    WHEEL_DIAMETER_FEEDBACK_SETTLE_SECONDS,
)


def wheel_diameter_feedback_settle_seconds(center_crossing, settle_crossing=None):
    effective_crossing = center_crossing if settle_crossing is None else settle_crossing
    return (
        WHEEL_DIAMETER_CENTER_FEEDBACK_SETTLE_SECONDS
        if effective_crossing
        else WHEEL_DIAMETER_FEEDBACK_SETTLE_SECONDS
    )


def wheel_diameter_detect_feedback_handle(
    area,
    center_crossing,
    settle_crossing,
    detect_handle_raw_for_area_fn,
    expected_handle=None,
    expected_axis=None,
):
    time.sleep(wheel_diameter_feedback_settle_seconds(center_crossing, settle_crossing))
    return detect_handle_raw_for_area_fn(
        area,
        expected_handle=expected_handle if center_crossing else None,
        expected_axis=expected_axis,
    )


__all__ = [
    'wheel_diameter_detect_feedback_handle',
    'wheel_diameter_feedback_settle_seconds',
]
