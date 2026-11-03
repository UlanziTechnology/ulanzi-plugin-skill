"""Horizontal-slider target layout inference for DaVinci color controls."""

from .config import (
    HORIZONTAL_SLIDER_SEARCH_BOTTOM_GAP,
    HORIZONTAL_SLIDER_SEARCH_SIDE_MARGIN,
    HORIZONTAL_SLIDER_SEARCH_TOP_GAP,
    SLIDER_OVERLAY_MARGIN,
    SLIDER_TARGET_HEIGHT,
    SLIDER_TARGET_VERTICAL_GAP,
    SLIDER_TRACK_OVERLAY_SIDE_PADDING,
    SLIDER_TRACK_OVERLAY_VERTICAL_PADDING,
)


def _row_bounds(row_inputs):
    left = min(inp['frame'][0] for inp in row_inputs)
    right = max(inp['frame'][0] + inp['frame'][2] for inp in row_inputs)
    top = min(inp['frame'][1] for inp in row_inputs)
    bottom = max(inp['frame'][1] + inp['frame'][3] for inp in row_inputs)
    return left, top, right, bottom


def _detect_track(wheel_area, row_inputs, row_bottom, search_bottom, detect_track_fn):
    if not detect_track_fn:
        return None

    wheel_x = wheel_area['x']
    wheel_w = wheel_area['w']
    row_left, _row_top, row_right, _row_bottom = _row_bounds(row_inputs)
    return _detect_track_in_span(
        min(wheel_x, row_left),
        max(wheel_x + wheel_w, row_right),
        row_bottom,
        search_bottom,
        detect_track_fn,
    )


def _detect_track_in_span(span_left, span_right, row_bottom, search_bottom, detect_track_fn):
    if not detect_track_fn:
        return None

    search_left = span_left - HORIZONTAL_SLIDER_SEARCH_SIDE_MARGIN
    search_right = span_right + HORIZONTAL_SLIDER_SEARCH_SIDE_MARGIN
    search_top = row_bottom + HORIZONTAL_SLIDER_SEARCH_TOP_GAP
    search_lower = min(search_bottom, row_bottom + HORIZONTAL_SLIDER_SEARCH_BOTTOM_GAP)
    search_rect = (
        search_left,
        search_top,
        max(1, search_right - search_left),
        max(1, search_lower - search_top),
    )
    return detect_track_fn(search_rect)


def _fallback_slider_bounds(wheel_area, row_inputs):
    wheel_x = wheel_area['x']
    wheel_w = wheel_area['w']
    row_left, _row_top, row_right, _row_bottom = _row_bounds(row_inputs)
    row_width = max(1, row_right - row_left)
    row_center = (row_left + row_right) / 2
    row_based_width = row_width * 0.9
    wheel_based_width = max(1, wheel_w - 8)
    slider_w = max(wheel_based_width, row_based_width)
    slider_x = row_center - slider_w / 2
    return slider_x, slider_w


def make_slider_target(wheel_area, numeric_inputs, *, detect_track_fn=None):
    wheel_x = wheel_area['x']
    wheel_y = wheel_area['y']
    wheel_w = wheel_area['w']
    wheel_h = wheel_area['h']
    wheel_bottom = wheel_y + wheel_h
    search_bottom = wheel_bottom + 110
    candidate_inputs = [
        inp for inp in numeric_inputs
        if wheel_x - 20 <= inp['frame'][0] + inp['frame'][2] / 2 <= wheel_x + wheel_w + 20
        and wheel_bottom <= inp['frame'][1] <= search_bottom
    ]

    if not candidate_inputs:
        return None

    first_row_y = min(inp['frame'][1] for inp in candidate_inputs)
    row_inputs = [
        inp for inp in candidate_inputs
        if abs(inp['frame'][1] - first_row_y) <= 8
    ]
    row_bottom = max(inp['frame'][1] + inp['frame'][3] for inp in row_inputs)
    track = _detect_track(
        wheel_area,
        row_inputs,
        row_bottom,
        search_bottom,
        detect_track_fn,
    )
    if track:
        slider_x = track['x']
        slider_w = max(1, track['w'])
        center_y = track['y'] + track['h'] / 2
        slider_y = center_y - SLIDER_TARGET_HEIGHT / 2
        source_frame = (track['x'], track['y'], track['w'], track['h'])
        overlay_x = track['x'] - SLIDER_TRACK_OVERLAY_SIDE_PADDING
        overlay_y = track['y'] - SLIDER_TRACK_OVERLAY_VERTICAL_PADDING
        overlay_w = track['w'] + SLIDER_TRACK_OVERLAY_SIDE_PADDING * 2
        overlay_h = track['h'] + SLIDER_TRACK_OVERLAY_VERTICAL_PADDING * 2
    else:
        slider_x, slider_w = _fallback_slider_bounds(wheel_area, row_inputs)
        slider_y = row_bottom + SLIDER_TARGET_VERTICAL_GAP
        center_y = slider_y + SLIDER_TARGET_HEIGHT / 2
        source_frame = (slider_x, slider_y, slider_w, SLIDER_TARGET_HEIGHT)
        overlay_x = slider_x - SLIDER_OVERLAY_MARGIN
        overlay_y = slider_y - SLIDER_OVERLAY_MARGIN
        overlay_w = slider_w + SLIDER_OVERLAY_MARGIN * 2
        overlay_h = SLIDER_TARGET_HEIGHT + SLIDER_OVERLAY_MARGIN * 2
    slider_h = SLIDER_TARGET_HEIGHT
    if slider_y > search_bottom:
        return None

    name = f"{wheel_area['name']} Slider"
    return {
        'id': f"slider:{wheel_area['name']}",
        'name': name,
        'type': 'slider',
        'x': slider_x,
        'y': slider_y,
        'w': slider_w,
        'h': slider_h,
        'overlay_x': overlay_x,
        'overlay_y': overlay_y,
        'overlay_w': overlay_w,
        'overlay_h': overlay_h,
        'center_x': slider_x + slider_w / 2,
        'center_y': center_y,
        'source_frame': source_frame,
        'priority': 10,
    }


def make_slider_target_from_numeric_group(
    name,
    row_inputs,
    *,
    detect_track_fn=None,
    target_id=None,
    priority=10,
):
    if not row_inputs:
        return None

    row_left, _row_top, row_right, row_bottom = _row_bounds(row_inputs)
    row_width = max(1, row_right - row_left)
    search_bottom = row_bottom + HORIZONTAL_SLIDER_SEARCH_BOTTOM_GAP
    track = _detect_track_in_span(
        row_left,
        row_right,
        row_bottom,
        search_bottom,
        detect_track_fn,
    )
    if track:
        slider_x = track['x']
        slider_w = max(1, track['w'])
        center_y = track['y'] + track['h'] / 2
        slider_y = center_y - SLIDER_TARGET_HEIGHT / 2
        source_frame = (track['x'], track['y'], track['w'], track['h'])
        overlay_x = track['x'] - SLIDER_TRACK_OVERLAY_SIDE_PADDING
        overlay_y = track['y'] - SLIDER_TRACK_OVERLAY_VERTICAL_PADDING
        overlay_w = track['w'] + SLIDER_TRACK_OVERLAY_SIDE_PADDING * 2
        overlay_h = track['h'] + SLIDER_TRACK_OVERLAY_VERTICAL_PADDING * 2
    else:
        row_center = (row_left + row_right) / 2
        slider_w = max(1, row_width * 0.9)
        slider_x = row_center - slider_w / 2
        slider_y = row_bottom + SLIDER_TARGET_VERTICAL_GAP
        center_y = slider_y + SLIDER_TARGET_HEIGHT / 2
        source_frame = (slider_x, slider_y, slider_w, SLIDER_TARGET_HEIGHT)
        overlay_x = slider_x - SLIDER_OVERLAY_MARGIN
        overlay_y = slider_y - SLIDER_OVERLAY_MARGIN
        overlay_w = slider_w + SLIDER_OVERLAY_MARGIN * 2
        overlay_h = SLIDER_TARGET_HEIGHT + SLIDER_OVERLAY_MARGIN * 2

    return {
        'id': target_id or f"slider:{name}:{round(row_left)}:{round(row_bottom)}",
        'name': f"{name} Slider",
        'type': 'slider',
        'x': slider_x,
        'y': slider_y,
        'w': slider_w,
        'h': SLIDER_TARGET_HEIGHT,
        'overlay_x': overlay_x,
        'overlay_y': overlay_y,
        'overlay_w': overlay_w,
        'overlay_h': overlay_h,
        'center_x': slider_x + slider_w / 2,
        'center_y': center_y,
        'source_frame': source_frame,
        'priority': priority,
    }


__all__ = [
    'make_slider_target',
    'make_slider_target_from_numeric_group',
]
