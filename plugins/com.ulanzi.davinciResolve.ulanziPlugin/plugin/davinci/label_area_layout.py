"""Shared target-area layout helpers for DaVinci labels and numeric inputs."""

from .config import (
    SELECTABLE_OVERLAY_MARGIN,
    SELECTABLE_TARGET_MARGIN,
    WHEEL_OVERLAY_HORIZONTAL_MARGIN,
    WHEEL_OVERLAY_VERTICAL_MARGIN,
)


LABEL_WHEEL_MIN_HEIGHT = 80
LABEL_WHEEL_FALLBACK_HEIGHT = 140


def target_from_rect(
    target_id,
    target_type,
    name,
    rect,
    margin=None,
    overlay_margin=None,
):
    if margin is None:
        margin = SELECTABLE_TARGET_MARGIN
    if overlay_margin is None:
        overlay_margin = SELECTABLE_OVERLAY_MARGIN

    x, y, w, h = rect
    target_x = x - margin
    target_y = y - margin
    target_w = max(1, w + margin * 2)
    target_h = max(1, h + margin * 2)
    return {
        'id': target_id,
        'name': name,
        'type': target_type,
        'x': target_x,
        'y': target_y,
        'w': target_w,
        'h': target_h,
        'overlay_x': x - overlay_margin,
        'overlay_y': y - overlay_margin,
        'overlay_w': w + overlay_margin * 2,
        'overlay_h': h + overlay_margin * 2,
        'center_x': target_x + target_w / 2,
        'center_y': target_y + target_h / 2,
        'source_frame': rect,
        'priority': 10,
    }


def is_wheel_value_numeric(rect, wheel_areas):
    x, y, w, _h = rect
    center_x = x + w / 2
    for wheel in wheel_areas:
        wheel_bottom = wheel['y'] + wheel['h']
        if (
            wheel['x'] - 20 <= center_x <= wheel['x'] + wheel['w'] + 20
            and wheel_bottom <= y <= wheel_bottom + 45
        ):
            return True
    return False


def infer_label_wheel_areas(labels, numeric_inputs):
    areas = []
    for label in labels:
        frame = label['frame']
        label_x, label_y, label_w, label_h = frame
        label_center_x = label_x + label_w / 2

        nearby_inputs = [
            inp for inp in numeric_inputs
            if abs((inp['frame'][0] + inp['frame'][2] / 2) - label_center_x) < label_w * 1.5
            and inp['frame'][1] > label_y + label_h
        ]

        area_top = label_y + label_h + 5
        if nearby_inputs:
            input_min_y = min(inp['frame'][1] for inp in nearby_inputs)
            area_bottom = input_min_y - 5
            if area_bottom - area_top < LABEL_WHEEL_MIN_HEIGHT:
                area_bottom = area_top + LABEL_WHEEL_FALLBACK_HEIGHT
        else:
            area_bottom = area_top + LABEL_WHEEL_FALLBACK_HEIGHT

        area_height = area_bottom - area_top
        if area_height < LABEL_WHEEL_MIN_HEIGHT:
            area_height = LABEL_WHEEL_MIN_HEIGHT
        area_width = max(area_height, label_w)
        area_x = label_x + (label_w - area_width) / 2
        area_y = area_top

        areas.append({
            'id': f"wheel:{label['name']}",
            'name': label['name'],
            'type': 'wheel',
            'x': area_x,
            'y': area_y,
            'w': area_width,
            'h': area_height,
            'overlay_x': area_x - WHEEL_OVERLAY_HORIZONTAL_MARGIN,
            'overlay_y': area_y - WHEEL_OVERLAY_VERTICAL_MARGIN,
            'overlay_w': area_width + WHEEL_OVERLAY_HORIZONTAL_MARGIN * 2,
            'overlay_h': area_height + WHEEL_OVERLAY_VERTICAL_MARGIN * 2,
            'center_x': area_x + area_width / 2,
            'center_y': area_y + area_height / 2,
            'label_frame': frame,
            'source': 'label',
            'priority': 0,
        })
    return areas
