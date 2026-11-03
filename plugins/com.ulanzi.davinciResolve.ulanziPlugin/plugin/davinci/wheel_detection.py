"""Pixel classification and candidate scoring for wheel controls."""

import math

from .config import (
    HANDLE_COLOR_MAX,
    HANDLE_COLOR_MIN,
    HANDLE_TOLERANCE,
    HORIZONTAL_SLIDER_TRACK_MAX_HEIGHT,
    HORIZONTAL_SLIDER_TRACK_MIN_DARK_FRACTION,
    HORIZONTAL_SLIDER_TRACK_MIN_HEIGHT,
    HORIZONTAL_SLIDER_TRACK_MIN_WIDTH,
    HORIZONTAL_SLIDER_TRACK_ROW_GAP,
    VERTICAL_SLIDER_MIN_HEIGHT,
    VERTICAL_SLIDER_TRACK_COLUMN_GAP,
    VERTICAL_SLIDER_TRACK_DARK_CHANNEL_MAX,
    VERTICAL_SLIDER_TRACK_DARK_LUMA_MAX,
    VERTICAL_SLIDER_TRACK_MAX_WIDTH,
    VERTICAL_SLIDER_TRACK_MIN_DARK_FRACTION,
    VERTICAL_SLIDER_TRACK_MIN_WIDTH,
    WHEEL_CIRCLE_TRIM_FRACTION,
    WHEEL_COLOR_BORDER_IGNORE,
    WHEEL_COLOR_BRIGHTNESS_MIN,
    WHEEL_COLOR_COMPONENT_MIN_PIXELS,
    WHEEL_COLOR_COMPONENT_MIN_SIZE,
    WHEEL_COLOR_MIN_PIXELS,
    WHEEL_COLOR_SAMPLE_STEP,
    WHEEL_COLOR_SATURATION_MIN,
    WHEEL_CROSSHAIR_LINE_RADIUS_RATIO,
    WHEEL_CROSSHAIR_MAX_CHANNEL_SPREAD,
    WHEEL_CROSSHAIR_MIN_LUMA,
    WHEEL_CROSSHAIR_MIN_SCORE_RATIO,
    WHEEL_CROSSHAIR_SEARCH_RADIUS_RATIO,
    WHEEL_HANDLE_CENTER_IGNORE_RADIUS,
    WHEEL_HANDLE_COMPONENT_EDGE_ARC_RADIUS_RATIO,
    WHEEL_HANDLE_COMPONENT_EDGE_ARC_TANGENT_RATIO,
    WHEEL_HANDLE_COMPONENT_ARC_MIN_SIZE,
    WHEEL_HANDLE_COMPONENT_MAX_ASPECT_RATIO,
    WHEEL_HANDLE_COMPONENT_MAX_SIZE,
    WHEEL_HANDLE_COMPONENT_MIN_DOT_FILL_RATIO,
    WHEEL_HANDLE_EXPECTED_POSITION_TOLERANCE_PX,
    WHEEL_HANDLE_EXPECTED_RADIUS_TOLERANCE_PX,
    WHEEL_HANDLE_OUTER_TOLERANCE,
    WHEEL_RADIUS_DISTANCE_MIN_POINTS,
    WHEEL_RADIUS_DISTANCE_PERCENTILE,
)


def get_pixel_color(pixel_data, x, y, bytes_per_row, bytes_per_pixel):
    offset = y * bytes_per_row + x * bytes_per_pixel
    if offset + 3 > len(pixel_data):
        return None
    r = pixel_data[offset]
    g = pixel_data[offset + 1]
    b = pixel_data[offset + 2]
    return (r, g, b)


def is_color_in_range(rgb, min_rgb, max_rgb, tolerance=0):
    r, g, b = rgb[:3]
    min_r, min_g, min_b = min_rgb
    max_r, max_g, max_b = max_rgb
    return (
        min_r - tolerance <= r <= max_r + tolerance
        and min_g - tolerance <= g <= max_g + tolerance
        and min_b - tolerance <= b <= max_b + tolerance
    )


def _trimmed_bounds(values, trim_fraction):
    if not values:
        return None
    ordered = sorted(values)
    trim_count = int(len(ordered) * trim_fraction)
    if trim_count * 2 >= len(ordered):
        trim_count = 0
    return ordered[trim_count], ordered[len(ordered) - trim_count - 1]


def _is_wheel_color_pixel(color):
    if not color:
        return False
    r, g, b = color
    max_channel = max(r, g, b)
    min_channel = min(r, g, b)
    return (
        max_channel >= WHEEL_COLOR_BRIGHTNESS_MIN
        and max_channel - min_channel >= WHEEL_COLOR_SATURATION_MIN
    )


def _pixel_luma(color):
    if not color:
        return 0.0
    r, g, b = color
    return 0.299 * r + 0.587 * g + 0.114 * b


def _crosshair_pixel_strength(pixel_data, x, y, width, height, bytes_per_row, bytes_per_pixel, orientation):
    color = get_pixel_color(pixel_data, x, y, bytes_per_row, bytes_per_pixel)
    if not color:
        return 0.0

    r, g, b = color
    channel_spread = max(r, g, b) - min(r, g, b)
    luma = _pixel_luma(color)
    if channel_spread > WHEEL_CROSSHAIR_MAX_CHANNEL_SPREAD or luma < WHEEL_CROSSHAIR_MIN_LUMA:
        return 0.0

    neighbor_lumas = []
    for offset in (-3, 3):
        if orientation == 'horizontal':
            nx, ny = x, y + offset
        else:
            nx, ny = x + offset, y
        if 0 <= nx < width and 0 <= ny < height:
            neighbor_lumas.append(_pixel_luma(get_pixel_color(
                pixel_data,
                nx,
                ny,
                bytes_per_row,
                bytes_per_pixel,
            )))

    contrast = 0.0
    if neighbor_lumas:
        contrast = luma - (sum(neighbor_lumas) / len(neighbor_lumas))

    if contrast < 4.0 and luma < 115:
        return 0.0

    neutral_score = (WHEEL_CROSSHAIR_MAX_CHANNEL_SPREAD - channel_spread) / WHEEL_CROSSHAIR_MAX_CHANNEL_SPREAD
    contrast_score = max(0.0, min(contrast, 55.0)) / 55.0
    brightness_score = max(0.0, min(luma - WHEEL_CROSSHAIR_MIN_LUMA, 100.0)) / 100.0
    return 0.55 + neutral_score * 0.65 + contrast_score * 0.75 + brightness_score * 0.25


def _score_crosshair_line(pixel_data, width, height, bytes_per_row, bytes_per_pixel, orientation, position, center_x, center_y, line_radius):
    total = 0.0
    count = 0

    if orientation == 'horizontal':
        y = int(round(position))
        if y < 0 or y >= height:
            return 0.0, 0
        start = max(0, int(round(center_x - line_radius)))
        end = min(width - 1, int(round(center_x + line_radius)))
        for x in range(start, end + 1):
            distance = abs(x - center_x)
            if distance > line_radius:
                continue
            total += _crosshair_pixel_strength(
                pixel_data, x, y, width, height, bytes_per_row, bytes_per_pixel, orientation
            )
            count += 1
    else:
        x = int(round(position))
        if x < 0 or x >= width:
            return 0.0, 0
        start = max(0, int(round(center_y - line_radius)))
        end = min(height - 1, int(round(center_y + line_radius)))
        for y in range(start, end + 1):
            distance = abs(y - center_y)
            if distance > line_radius:
                continue
            total += _crosshair_pixel_strength(
                pixel_data, x, y, width, height, bytes_per_row, bytes_per_pixel, orientation
            )
            count += 1

    return total / max(1, count), count


def _weighted_crosshair_peak(candidates):
    if not candidates:
        return None

    best = max(candidates, key=lambda item: item['score'])
    if best['score'] < WHEEL_CROSSHAIR_MIN_SCORE_RATIO:
        return None

    threshold = max(WHEEL_CROSSHAIR_MIN_SCORE_RATIO, best['score'] * 0.72)
    peak = [
        candidate for candidate in candidates
        if abs(candidate['position'] - best['position']) <= 3
        and candidate['score'] >= threshold
    ]
    total_score = sum(candidate['score'] for candidate in peak)
    if total_score <= 0:
        return best

    return {
        'position': sum(candidate['position'] * candidate['score'] for candidate in peak) / total_score,
        'score': best['score'],
        'samples': best['samples'],
    }


def _detect_wheel_crosshair_center(pixel_data, width, height, bytes_per_row, bytes_per_pixel, rough_center_x, rough_center_y, rough_radius):
    if rough_radius < 30:
        return None

    search_radius = max(7, rough_radius * WHEEL_CROSSHAIR_SEARCH_RADIUS_RATIO)
    line_radius = max(22, rough_radius * WHEEL_CROSSHAIR_LINE_RADIUS_RATIO)

    row_candidates = []
    row_start = max(0, int(round(rough_center_y - search_radius)))
    row_end = min(height - 1, int(round(rough_center_y + search_radius)))
    for y in range(row_start, row_end + 1):
        score, samples = _score_crosshair_line(
            pixel_data,
            width,
            height,
            bytes_per_row,
            bytes_per_pixel,
            'horizontal',
            y,
            rough_center_x,
            rough_center_y,
            line_radius,
        )
        row_candidates.append({'position': y, 'score': score, 'samples': samples})

    column_candidates = []
    column_start = max(0, int(round(rough_center_x - search_radius)))
    column_end = min(width - 1, int(round(rough_center_x + search_radius)))
    for x in range(column_start, column_end + 1):
        score, samples = _score_crosshair_line(
            pixel_data,
            width,
            height,
            bytes_per_row,
            bytes_per_pixel,
            'vertical',
            x,
            rough_center_x,
            rough_center_y,
            line_radius,
        )
        column_candidates.append({'position': x, 'score': score, 'samples': samples})

    row_peak = _weighted_crosshair_peak(row_candidates)
    column_peak = _weighted_crosshair_peak(column_candidates)
    if not row_peak or not column_peak:
        return None

    return {
        'center_x': column_peak['position'],
        'center_y': row_peak['position'],
        'horizontal_score': row_peak['score'],
        'vertical_score': column_peak['score'],
    }


def _choose_wheel_color_component(sampled_points, area_width, area_height, sample_step):
    if not sampled_points:
        return None

    visited = set()
    best = None
    area_center_x = area_width / 2
    area_center_y = area_height / 2

    for grid_point in sampled_points:
        if grid_point in visited:
            continue

        stack = [grid_point]
        visited.add(grid_point)
        component = []
        while stack:
            current = stack.pop()
            component.append(sampled_points[current])
            gx, gy = current
            for nx in range(gx - 1, gx + 2):
                for ny in range(gy - 1, gy + 2):
                    neighbor = (nx, ny)
                    if neighbor in sampled_points and neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)

        if len(component) < WHEEL_COLOR_COMPONENT_MIN_PIXELS:
            continue

        xs = [point[0] for point in component]
        ys = [point[1] for point in component]
        x_bounds = _trimmed_bounds(xs, WHEEL_CIRCLE_TRIM_FRACTION)
        y_bounds = _trimmed_bounds(ys, WHEEL_CIRCLE_TRIM_FRACTION)
        if not x_bounds or not y_bounds:
            continue

        min_x, max_x = x_bounds
        min_y, max_y = y_bounds
        box_w = max_x - min_x
        box_h = max_y - min_y
        if box_w < WHEEL_COLOR_COMPONENT_MIN_SIZE or box_h < WHEEL_COLOR_COMPONENT_MIN_SIZE:
            continue

        larger = max(box_w, box_h)
        smaller = max(1, min(box_w, box_h))
        square_ratio = smaller / larger
        if square_ratio < 0.58:
            continue

        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        distance_from_area_center = math.hypot(
            center_x - area_center_x,
            center_y - area_center_y,
        )
        score = (
            len(component) * sample_step
            + smaller * 2.0
            + square_ratio * 120.0
            - distance_from_area_center * 0.35
        )

        if best is None or score > best['score']:
            best = {
                'min_x': min_x,
                'max_x': max_x,
                'min_y': min_y,
                'max_y': max_y,
                'score': score,
                'count': len(component),
                'points': component,
            }

    return best


def _handle_expected_context(expected_handle, wheel_geometry):
    if not expected_handle or not wheel_geometry:
        return None
    try:
        expected_x = float(expected_handle['x'])
        expected_y = float(expected_handle['y'])
        center_x = float(wheel_geometry['wheel_center_x'])
        center_y = float(wheel_geometry['wheel_center_y'])
        wheel_radius = float(wheel_geometry['wheel_radius'])
    except (KeyError, TypeError, ValueError):
        return None
    expected_radius = math.hypot(expected_x - center_x, expected_y - center_y)
    if not math.isfinite(expected_radius):
        return None
    return {
        'x': expected_x,
        'y': expected_y,
        'radius': expected_radius,
        'wheel_radius': wheel_radius,
        'allow_center_candidate': bool(expected_handle.get('allow_center_candidate')),
    }


def _handle_expected_axis_context(expected_axis, wheel_geometry):
    if not expected_axis or not wheel_geometry:
        return None
    try:
        axis_angle = float(expected_axis['axis_angle'])
        axis_tolerance = float(expected_axis['axis_tolerance'])
        center_x = float(wheel_geometry['wheel_center_x'])
        center_y = float(wheel_geometry['wheel_center_y'])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        not math.isfinite(axis_angle)
        or not math.isfinite(axis_tolerance)
        or axis_tolerance <= 0
    ):
        return None
    return {
        'axis_angle': axis_angle,
        'axis_tolerance': axis_tolerance,
        'center_x': center_x,
        'center_y': center_y,
        'cos': math.cos(axis_angle),
        'sin': math.sin(axis_angle),
    }


def _component_radial_tangent_spans(component, center_x, center_y, component_x, component_y):
    dx = component_x - center_x
    dy = component_y - center_y
    distance = math.hypot(dx, dy)
    if distance < 1:
        return None
    radial_x = dx / distance
    radial_y = dy / distance
    tangent_x = -radial_y
    tangent_y = radial_x
    radial_values = []
    tangent_values = []
    for px, py in component:
        local_x = px - component_x
        local_y = py - component_y
        radial_values.append(local_x * radial_x + local_y * radial_y)
        tangent_values.append(local_x * tangent_x + local_y * tangent_y)
    return {
        'radial_span': max(radial_values) - min(radial_values),
        'tangent_span': max(tangent_values) - min(tangent_values),
    }


def _choose_handle_component(handles, wheel_geometry=None, expected_handle=None, expected_axis=None):
    if not handles:
        return None

    expected_context = _handle_expected_context(expected_handle, wheel_geometry)
    expected_axis_context = _handle_expected_axis_context(expected_axis, wheel_geometry)
    points = {(int(round(x)), int(round(y))) for x, y in handles}
    visited = set()
    components = []
    for point in points:
        if point in visited:
            continue
        stack = [point]
        visited.add(point)
        component = []
        while stack:
            current = stack.pop()
            component.append(current)
            px, py = current
            for nx in range(px - 1, px + 2):
                for ny in range(py - 1, py + 2):
                    neighbor = (nx, ny)
                    if neighbor in points and neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)
        components.append(component)

    candidates = []
    for component in components:
        xs = [point[0] for point in component]
        ys = [point[1] for point in component]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width = max_x - min_x + 1
        height = max_y - min_y + 1
        max_size = max(width, height)
        center_x = sum(xs) / len(xs)
        center_y = sum(ys) / len(ys)

        if max_size > WHEEL_HANDLE_COMPONENT_MAX_SIZE:
            continue

        min_size = min(width, height)
        aspect_ratio = max_size / max(1, min_size)
        fill_ratio = len(component) / max(1, width * height)
        if (
            max_size >= WHEEL_HANDLE_COMPONENT_ARC_MIN_SIZE
            and aspect_ratio >= WHEEL_HANDLE_COMPONENT_MAX_ASPECT_RATIO
        ):
            continue

        score = min(len(component), 24)
        score -= abs(width - height) * 1.5
        score -= max(0, max_size - 10) * 2.0
        score += min(fill_ratio, 0.85) * 4.0

        if wheel_geometry:
            distance = math.hypot(
                center_x - wheel_geometry['wheel_center_x'],
                center_y - wheel_geometry['wheel_center_y'],
            )
            wheel_radius = wheel_geometry['wheel_radius']
            if distance > wheel_radius + WHEEL_HANDLE_OUTER_TOLERANCE:
                continue
            spans = _component_radial_tangent_spans(
                component,
                wheel_geometry['wheel_center_x'],
                wheel_geometry['wheel_center_y'],
                center_x,
                center_y,
            )
            if spans:
                radial_span = spans['radial_span']
                tangent_span = spans['tangent_span']
                edge_candidate = distance >= wheel_radius * WHEEL_HANDLE_COMPONENT_EDGE_ARC_RADIUS_RATIO
                tangent_arc_like = (
                    edge_candidate
                    and max_size >= WHEEL_HANDLE_COMPONENT_ARC_MIN_SIZE
                    and tangent_span >= max(
                        radial_span * WHEEL_HANDLE_COMPONENT_EDGE_ARC_TANGENT_RATIO,
                        WHEEL_HANDLE_COMPONENT_ARC_MIN_SIZE - 1,
                    )
                    and fill_ratio < max(WHEEL_HANDLE_COMPONENT_MIN_DOT_FILL_RATIO, 0.58)
                )
                box_arc_like = (
                    edge_candidate
                    and max_size >= WHEEL_HANDLE_COMPONENT_ARC_MIN_SIZE
                    and aspect_ratio >= 1.9
                    and fill_ratio < 0.58
                )
                if tangent_arc_like or box_arc_like:
                    continue
                if edge_candidate and tangent_span > radial_span:
                    score -= (tangent_span - radial_span) * 0.8
            elif fill_ratio < WHEEL_HANDLE_COMPONENT_MIN_DOT_FILL_RATIO:
                score -= 2.0
            if distance > wheel_radius * 0.96:
                score -= (distance - wheel_radius * 0.96) * 3.0
            elif distance > 5:
                score += min(distance, wheel_radius * 0.65) * 0.01
        else:
            distance = None

        expected_position_delta = None
        expected_radius_delta = None
        expected_axis_cross_delta = None
        expected_axis_signed_radius = None
        if expected_axis_context and wheel_geometry:
            axis_dx = center_x - expected_axis_context['center_x']
            axis_dy = center_y - expected_axis_context['center_y']
            expected_axis_cross_delta = abs(
                -axis_dx * expected_axis_context['sin']
                + axis_dy * expected_axis_context['cos']
            )
            expected_axis_signed_radius = (
                axis_dx * expected_axis_context['cos']
                + axis_dy * expected_axis_context['sin']
            )
            score -= expected_axis_cross_delta * 0.6

        if expected_context and distance is not None:
            expected_position_delta = math.hypot(
                center_x - expected_context['x'],
                center_y - expected_context['y'],
            )
            expected_radius_delta = abs(distance - expected_context['radius'])
            score -= expected_position_delta * 0.25
            score -= expected_radius_delta * 0.9

        candidates.append({
            'x': center_x,
            'y': center_y,
            'count': len(component),
            'score': score,
            'distance': distance,
            'expected_position_delta': expected_position_delta,
            'expected_radius_delta': expected_radius_delta,
            'expected_axis_cross_delta': expected_axis_cross_delta,
            'expected_axis_signed_radius': expected_axis_signed_radius,
        })

    if candidates:
        if expected_axis_context:
            axis_candidates = [
                candidate for candidate in candidates
                if candidate.get('expected_axis_cross_delta') is not None
                and candidate['expected_axis_cross_delta'] <= expected_axis_context['axis_tolerance']
            ]
            if not axis_candidates:
                return None
            candidates = axis_candidates

        if expected_context:
            position_limit = max(
                WHEEL_HANDLE_EXPECTED_POSITION_TOLERANCE_PX,
                expected_context['wheel_radius'] * 0.32,
            )
            radius_limit = max(
                WHEEL_HANDLE_EXPECTED_RADIUS_TOLERANCE_PX,
                expected_context['radius'] * 0.36,
            )
            expected_candidates = [
                candidate for candidate in candidates
                if candidate.get('expected_position_delta') is not None
                and candidate['expected_position_delta'] <= position_limit
                and candidate['expected_radius_delta'] <= radius_limit
            ]
            if not expected_candidates:
                return None
            candidates = expected_candidates

        if wheel_geometry:
            preserve_expected_center = (
                expected_context
                and (
                    expected_context['radius'] < WHEEL_HANDLE_CENTER_IGNORE_RADIUS
                    or expected_context.get('allow_center_candidate')
                )
            )
            off_center = [
                candidate for candidate in candidates
                if candidate.get('distance') is None
                or candidate['distance'] >= WHEEL_HANDLE_CENTER_IGNORE_RADIUS
            ]
            if off_center and not preserve_expected_center:
                candidates = off_center

        best = max(candidates, key=lambda item: item['score'])
        best.pop('distance', None)
        best.pop('expected_position_delta', None)
        best.pop('expected_radius_delta', None)
        best.pop('expected_axis_cross_delta', None)
        best.pop('expected_axis_signed_radius', None)
        return best

    return None


def _is_vertical_slider_marker_pixel(color):
    if not color:
        return False

    r, g, b = color
    max_channel = max(r, g, b)
    min_channel = min(r, g, b)
    luma = _pixel_luma(color)

    if luma >= 170 and max_channel - min_channel <= 80:
        return True
    if r >= 170 and r - max(g, b) >= 55:
        return True
    if g >= 150 and g - max(r, b) >= 45:
        return True
    if b >= 150 and b - max(r, g) >= 45:
        return True
    return False


def _is_vertical_slider_track_pixel(color):
    if not color:
        return False
    return (
        max(color) <= VERTICAL_SLIDER_TRACK_DARK_CHANNEL_MAX
        and _pixel_luma(color) <= VERTICAL_SLIDER_TRACK_DARK_LUMA_MAX
    )


def _find_contiguous_number_groups(values, max_gap=1):
    if not values:
        return []
    groups = []
    current = [values[0]]
    for value in values[1:]:
        if value <= current[-1] + max_gap:
            current.append(value)
        else:
            groups.append(current)
            current = [value]
    groups.append(current)
    return groups


def detect_wheel_circle_geometry(area, capture_screen_region_fn, debug_slow_fn=None):
    """Estimate the real color-wheel center/radius from saturated wheel pixels."""
    area_x = area['x']
    area_y = area['y']
    area_w = area['w']
    area_h = area['h']
    pixel_data, width, height, bytes_per_row, bytes_per_pixel = capture_screen_region_fn(
        area_x, area_y, area_w, area_h
    )

    if not pixel_data:
        return None

    xs = []
    ys = []
    sampled_points = {}
    step = max(1, WHEEL_COLOR_SAMPLE_STEP)
    border = max(WHEEL_COLOR_BORDER_IGNORE, int(min(width, height) * 0.02))
    for y in range(border, max(border, height - border), step):
        for x in range(border, max(border, width - border), step):
            color = get_pixel_color(pixel_data, x, y, bytes_per_row, bytes_per_pixel)
            if _is_wheel_color_pixel(color):
                xs.append(x)
                ys.append(y)
                sampled_points[(x // step, y // step)] = (x, y)

    if len(xs) < WHEEL_COLOR_MIN_PIXELS:
        return None

    component = _choose_wheel_color_component(sampled_points, width, height, step)
    if component:
        min_x = component['min_x']
        max_x = component['max_x']
        min_y = component['min_y']
        max_y = component['max_y']
        radius_points = component.get('points') or sampled_points.values()
    else:
        x_bounds = _trimmed_bounds(xs, WHEEL_CIRCLE_TRIM_FRACTION)
        y_bounds = _trimmed_bounds(ys, WHEEL_CIRCLE_TRIM_FRACTION)
        if not x_bounds or not y_bounds:
            return None

        min_x, max_x = x_bounds
        min_y, max_y = y_bounds
        radius_points = sampled_points.values()
    box_w = max_x - min_x
    box_h = max_y - min_y
    if box_w < 40 or box_h < 40:
        return None

    rough_center_x = (min_x + max_x) / 2
    rough_center_y = (min_y + max_y) / 2
    radius = max(box_w, box_h) / 2
    center_x = rough_center_x
    center_y = rough_center_y

    crosshair = _detect_wheel_crosshair_center(
        pixel_data,
        width,
        height,
        bytes_per_row,
        bytes_per_pixel,
        rough_center_x,
        rough_center_y,
        radius,
    )
    if crosshair:
        center_x = crosshair['center_x']
        center_y = crosshair['center_y']
        if debug_slow_fn:
            debug_slow_fn(
                "wheel crosshair center "
                f"local=({center_x:.1f},{center_y:.1f}) "
                f"scores=({crosshair['horizontal_score']:.2f},{crosshair['vertical_score']:.2f}) "
                f"rough=({rough_center_x:.1f},{rough_center_y:.1f})"
            )

    radius_samples = sorted(
        math.hypot(point_x - center_x, point_y - center_y)
        for point_x, point_y in radius_points
    )
    if len(radius_samples) >= WHEEL_RADIUS_DISTANCE_MIN_POINTS:
        sample_index = min(
            len(radius_samples) - 1,
            max(0, int((len(radius_samples) - 1) * WHEEL_RADIUS_DISTANCE_PERCENTILE)),
        )
        radius = max(radius, radius_samples[sample_index])

    return {
        'wheel_center_x': area_x + center_x,
        'wheel_center_y': area_y + center_y,
        'visual_center_x': area_x + rough_center_x,
        'visual_center_y': area_y + rough_center_y,
        'wheel_radius': radius,
    }


def detect_wheel_handle_in_region(
    area_x,
    area_y,
    area_w,
    *,
    capture_screen_region_fn,
    area_h=None,
    wheel_geometry=None,
    expected_handle=None,
    expected_axis=None,
):
    if area_h is None:
        area_h = area_w

    pixel_data, width, height, bytes_per_row, bytes_per_pixel = capture_screen_region_fn(
        area_x, area_y, area_w, area_h
    )

    if not pixel_data:
        return None

    handles = []

    for y in range(1, height - 1):
        for x in range(1, width - 1):
            match_count = 0
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    color = get_pixel_color(pixel_data, x + dx, y + dy, bytes_per_row, bytes_per_pixel)
                    if color and is_color_in_range(color, HANDLE_COLOR_MIN, HANDLE_COLOR_MAX, HANDLE_TOLERANCE):
                        match_count += 1

            if match_count >= 5:
                screen_x = area_x + x
                screen_y = area_y + y
                if wheel_geometry:
                    distance_from_center = math.hypot(
                        screen_x - wheel_geometry['wheel_center_x'],
                        screen_y - wheel_geometry['wheel_center_y'],
                    )
                    if distance_from_center > wheel_geometry['wheel_radius'] + WHEEL_HANDLE_OUTER_TOLERANCE:
                        continue
                handles.append((screen_x, screen_y))

    if not handles:
        return None

    return _choose_handle_component(handles, wheel_geometry, expected_handle, expected_axis)


def detect_vertical_slider_handle_in_area(area, capture_screen_region_fn):
    source_frame = area.get('source_frame')
    if source_frame:
        area_x, area_y, area_w, area_h = source_frame
    else:
        area_x, area_y, area_w, area_h = area['x'], area['y'], area['w'], area['h']

    pixel_data, width, height, bytes_per_row, bytes_per_pixel = capture_screen_region_fn(
        area_x,
        area_y,
        area_w,
        area_h,
    )
    if not pixel_data or width <= 0 or height <= 0:
        return None

    row_hits = []
    x_min = max(0, int(width * 0.12))
    x_max = min(width - 1, int(width * 0.88))
    min_hits = max(3, int((x_max - x_min + 1) * 0.16))

    for y in range(1, height - 1):
        xs = []
        for x in range(x_min, x_max + 1):
            if _is_vertical_slider_marker_pixel(
                get_pixel_color(pixel_data, x, y, bytes_per_row, bytes_per_pixel)
            ):
                xs.append(x)
        if len(xs) >= min_hits:
            row_hits.append({'y': y, 'count': len(xs), 'x': sum(xs) / len(xs)})

    if not row_hits:
        return None

    groups = []
    current = [row_hits[0]]
    for row in row_hits[1:]:
        if row['y'] <= current[-1]['y'] + 1:
            current.append(row)
        else:
            groups.append(current)
            current = [row]
    groups.append(current)

    def group_score(group):
        height_score = 12 - min(12, len(group))
        count_score = sum(item['count'] for item in group) / max(1, len(group))
        return height_score * 10 + count_score

    group = max(groups, key=group_score)
    value = area.get('value')
    try:
        numeric_value = float(value) if value not in (None, '') else 0.0
    except (TypeError, ValueError):
        numeric_value = 0.0

    if len(group) > 10:
        chosen = group[-1] if numeric_value < 0 else group[0]
    else:
        chosen = max(group, key=lambda item: item['count'])

    return {
        'x': area_x + chosen['x'],
        'y': area_y + chosen['y'],
        'count': chosen['count'],
    }


def detect_vertical_slider_tracks_in_region(search_rect, capture_screen_region_fn):
    search_x, search_y, search_w, search_h = search_rect
    pixel_data, width, height, bytes_per_row, bytes_per_pixel = capture_screen_region_fn(
        search_x,
        search_y,
        search_w,
        search_h,
    )
    if not pixel_data or width <= 0 or height <= 0:
        return []

    min_dark_pixels = max(
        int(height * VERTICAL_SLIDER_TRACK_MIN_DARK_FRACTION),
        int(VERTICAL_SLIDER_MIN_HEIGHT * 0.25),
    )
    column_hits = []
    for x in range(width):
        dark_count = 0
        for y in range(height):
            if _is_vertical_slider_track_pixel(
                get_pixel_color(pixel_data, x, y, bytes_per_row, bytes_per_pixel)
            ):
                dark_count += 1
        if dark_count >= min_dark_pixels:
            column_hits.append({'x': x, 'count': dark_count})

    if not column_hits:
        return []

    column_groups = []
    current = [column_hits[0]]
    for column in column_hits[1:]:
        if column['x'] <= current[-1]['x'] + VERTICAL_SLIDER_TRACK_COLUMN_GAP:
            current.append(column)
        else:
            column_groups.append(current)
            current = [column]
    column_groups.append(current)

    tracks = []
    for columns in column_groups:
        x0 = columns[0]['x']
        x1 = columns[-1]['x']
        track_w = x1 - x0 + 1
        if track_w < VERTICAL_SLIDER_TRACK_MIN_WIDTH or track_w > VERTICAL_SLIDER_TRACK_MAX_WIDTH:
            continue

        row_hits = []
        min_row_dark = max(2, int(track_w * 0.25))
        for y in range(height):
            dark_count = 0
            for x in range(x0, x1 + 1):
                if _is_vertical_slider_track_pixel(
                    get_pixel_color(pixel_data, x, y, bytes_per_row, bytes_per_pixel)
                ):
                    dark_count += 1
            if dark_count >= min_row_dark:
                row_hits.append(y)

        row_groups = _find_contiguous_number_groups(row_hits)
        if not row_groups:
            continue
        rows = max(row_groups, key=len)
        track_h = rows[-1] - rows[0] + 1
        if track_h < VERTICAL_SLIDER_MIN_HEIGHT:
            continue

        tracks.append({
            'x': search_x + x0,
            'y': search_y + rows[0],
            'w': track_w,
            'h': track_h,
            'score': sum(column['count'] for column in columns),
        })

    tracks.sort(key=lambda track: track['x'])
    return tracks


def detect_horizontal_slider_track_in_region(search_rect, capture_screen_region_fn):
    search_x, search_y, search_w, search_h = search_rect
    pixel_data, width, height, bytes_per_row, bytes_per_pixel = capture_screen_region_fn(
        search_x,
        search_y,
        search_w,
        search_h,
    )
    if not pixel_data or width <= 0 or height <= 0:
        return None

    min_dark_pixels = max(
        HORIZONTAL_SLIDER_TRACK_MIN_WIDTH,
        int(width * HORIZONTAL_SLIDER_TRACK_MIN_DARK_FRACTION),
    )
    row_hits = []
    for y in range(height):
        dark_count = 0
        for x in range(width):
            if _is_vertical_slider_track_pixel(
                get_pixel_color(pixel_data, x, y, bytes_per_row, bytes_per_pixel)
            ):
                dark_count += 1
        if dark_count >= min_dark_pixels:
            row_hits.append({'y': y, 'count': dark_count})

    if not row_hits:
        return None

    row_groups = []
    current = [row_hits[0]]
    for row in row_hits[1:]:
        if row['y'] <= current[-1]['y'] + HORIZONTAL_SLIDER_TRACK_ROW_GAP:
            current.append(row)
        else:
            row_groups.append(current)
            current = [row]
    row_groups.append(current)

    candidates = []
    for rows in row_groups:
        y0 = rows[0]['y']
        y1 = rows[-1]['y']
        track_h = y1 - y0 + 1
        if (
            track_h < HORIZONTAL_SLIDER_TRACK_MIN_HEIGHT
            or track_h > HORIZONTAL_SLIDER_TRACK_MAX_HEIGHT
        ):
            continue

        column_hits = []
        min_column_dark = max(2, int(track_h * 0.35))
        for x in range(width):
            dark_count = 0
            for y in range(y0, y1 + 1):
                if _is_vertical_slider_track_pixel(
                    get_pixel_color(pixel_data, x, y, bytes_per_row, bytes_per_pixel)
                ):
                    dark_count += 1
            if dark_count >= min_column_dark:
                column_hits.append(x)

        column_groups = _find_contiguous_number_groups(column_hits, max_gap=2)
        if not column_groups:
            continue
        columns = max(column_groups, key=len)
        track_w = columns[-1] - columns[0] + 1
        if track_w < HORIZONTAL_SLIDER_TRACK_MIN_WIDTH:
            continue

        candidates.append({
            'x': search_x + columns[0],
            'y': search_y + y0,
            'w': track_w,
            'h': track_h,
            'score': sum(row['count'] for row in rows) + track_w * track_h,
        })

    if not candidates:
        return None
    return max(candidates, key=lambda track: track['score'])


__all__ = [
    '_choose_handle_component',
    '_choose_wheel_color_component',
    '_crosshair_pixel_strength',
    '_detect_wheel_crosshair_center',
    '_is_vertical_slider_marker_pixel',
    '_is_vertical_slider_track_pixel',
    '_is_wheel_color_pixel',
    '_pixel_luma',
    '_find_contiguous_number_groups',
    '_score_crosshair_line',
    '_trimmed_bounds',
    '_weighted_crosshair_peak',
    'detect_horizontal_slider_track_in_region',
    'detect_wheel_circle_geometry',
    'detect_vertical_slider_handle_in_area',
    'detect_vertical_slider_tracks_in_region',
    'detect_wheel_handle_in_region',
    'get_pixel_color',
    'is_color_in_range',
]
