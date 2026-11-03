"""Pure geometry for Jianying color-wheel encoder gestures."""

import math


VALID_WHEEL_MODES = frozenset({"diameter", "orbit"})
DEFAULT_RESPONSE_GAIN = 0.15
MIN_RESPONSE_GAIN = 0.05
MAX_RESPONSE_GAIN = 0.50
MAX_CURSOR_DISTANCE_PER_EVENT = 96.0
CENTER_HANDLE_RADIUS = 1.5
MAX_DIAMETER_RADIUS_RATIO = 0.95


def normalize_wheel_mode(value, fallback="diameter"):
    value = str(value or "").strip().lower()
    return value if value in VALID_WHEEL_MODES else fallback


def _number(source, key, default=0.0):
    try:
        return float((source or {}).get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, minimum, maximum):
    return min(maximum, max(minimum, value))


def _geometry_signature(target):
    return (
        str((target or {}).get("key") or ""),
        round(_number(target, "centerX"), 1),
        round(_number(target, "centerY"), 1),
        round(_number(target, "wheelRadius"), 1),
        int(_number(target, "scanVersion", 0)),
    )


def _initial_state(target):
    center_x = _number(target, "centerX")
    center_y = _number(target, "centerY")
    radius = max(12.0, _number(target, "wheelRadius", 45.0))
    safe_radius = max(8.0, radius * MAX_DIAMETER_RADIUS_RATIO)
    handle_x = _number(target, "handleX", center_x)
    handle_y = _number(target, "handleY", center_y)
    dx = handle_x - center_x
    dy = handle_y - center_y
    actual_radius = math.hypot(dx, dy)
    # The recognizer may reacquire a manually positioned white point slightly
    # beyond our outward-planning limit. Keep its real coordinates: a fresh
    # mouse-down must land on that point so diameter and orbit gestures can
    # bring it back instead of pressing empty wheel space.
    angle = math.atan2(dy, dx) if actual_radius >= CENTER_HANDLE_RADIUS else -math.pi / 2
    return {
        "signature": _geometry_signature(target),
        "centerX": center_x,
        "centerY": center_y,
        "wheelRadius": radius,
        "safeRadius": safe_radius,
        "handleX": handle_x,
        "handleY": handle_y,
        "cursorX": handle_x,
        "cursorY": handle_y,
        "angle": angle,
        "radius": actual_radius,
        "lastMode": "",
    }


def _diameter_axis(dx, dy, radius):
    if radius < CENTER_HANDLE_RADIUS:
        return -math.pi / 2, 0.0
    angle = math.atan2(dy, dx)
    # Lock the gesture to one diameter. Crossing zero continues to the
    # opposite hue instead of stopping at the wheel centre.
    if math.sin(angle) > 0:
        return angle + math.pi, -radius
    return angle, radius


def _bounded_signed_radius(signed_radius, delta, limit):
    """Apply a diameter step without pushing an existing outer handle farther."""
    proposed = signed_radius + delta
    if signed_radius > limit:
        return _clamp(proposed, -limit, signed_radius)
    if signed_radius < -limit:
        return _clamp(proposed, signed_radius, limit)
    return _clamp(proposed, -limit, limit)


def _relative_drag_path(start_x, start_y, handle_dx, handle_dy, response_gain):
    response_gain = _clamp(
        float(response_gain or DEFAULT_RESPONSE_GAIN),
        MIN_RESPONSE_GAIN,
        MAX_RESPONSE_GAIN,
    )
    cursor_dx = handle_dx / response_gain
    cursor_dy = handle_dy / response_gain
    cursor_distance = math.hypot(cursor_dx, cursor_dy)
    if cursor_distance > MAX_CURSOR_DISTANCE_PER_EVENT:
        scale = MAX_CURSOR_DISTANCE_PER_EVENT / cursor_distance
        cursor_dx *= scale
        cursor_dy *= scale
        cursor_distance = MAX_CURSOR_DISTANCE_PER_EVENT
    if cursor_distance < 0.01:
        return [], 0.0, 0.0, 0.0, 0.0
    steps = max(2, min(18, int(math.ceil(cursor_distance / 6.0))))
    path = [
        (
            start_x + cursor_dx * index / steps,
            start_y + cursor_dy * index / steps,
        )
        for index in range(1, steps + 1)
    ]
    return (
        path,
        cursor_dx * response_gain,
        cursor_dy * response_gain,
        cursor_distance,
        response_gain,
    )


def _relative_orbit_path(start_x, start_y, radius, angle, delta, response_gain):
    """Sample the handle's circle in relative cursor coordinates.

    Limit arc length, not a chord: truncating a long chord pulls the handle
    toward the centre and makes the next orbit segment change speed/radius.
    """
    max_delta = MAX_CURSOR_DISTANCE_PER_EVENT * response_gain / radius
    delta = _clamp(delta, -max_delta, max_delta)
    distance = abs(delta) * radius / response_gain
    if distance < 0.01:
        return [], [], 0.0, 0.0, 0.0
    # A slow detent used to take 55 ms with just two or three mouse events.
    # Give small turns less latency and larger turns more interpolation time.
    duration = _clamp(abs(math.degrees(delta)) * 0.006, 0.024, 0.072)
    steps = max(4, int(math.ceil(distance / 4.0)), int(math.ceil(duration / 0.008)))
    start_dx, start_dy = radius * math.cos(angle), radius * math.sin(angle)
    angles = [angle + delta * index / steps for index in range(1, steps + 1)]
    path = [
        (
            start_x + (radius * math.cos(sample) - start_dx) / response_gain,
            start_y + (radius * math.sin(sample) - start_dy) / response_gain,
        )
        for sample in angles
    ]
    return path, angles, distance, delta, duration


def plan_wheel_motion(
    target,
    ticks,
    mode,
    sensitivity=1.0,
    state=None,
    response_gain=None,
):
    """Plan relative cursor movement and the resulting white-handle state."""
    mode = normalize_wheel_mode(mode)
    try:
        ticks = _clamp(float(ticks), -24.0, 24.0)
    except (TypeError, ValueError):
        ticks = 0.0
    try:
        sensitivity = _clamp(float(sensitivity), 0.25, 4.0)
    except (TypeError, ValueError):
        sensitivity = 1.0

    signature = _geometry_signature(target)
    if not isinstance(state, dict) or state.get("signature") != signature:
        state = _initial_state(target)
    else:
        state = dict(state)

    # Jianying treats a wheel drag as a low-gain relative XY gesture. The
    # cursor therefore moves farther than the white handle. Keep both states
    # separate; only a new mouse-down starts at the detected white handle.
    start_x = float(state.get("cursorX", state["handleX"]))
    start_y = float(state.get("cursorY", state["handleY"]))
    handle_start_x = float(state["handleX"])
    handle_start_y = float(state["handleY"])
    center_x = state["centerX"]
    center_y = state["centerY"]
    safe_radius = state["safeRadius"]
    try:
        response_gain = _clamp(
            float(response_gain),
            MIN_RESPONSE_GAIN,
            MAX_RESPONSE_GAIN,
        )
    except (TypeError, ValueError):
        response_gain = DEFAULT_RESPONSE_GAIN

    orbit_angles = []
    duration = 0.055
    if mode == "orbit":
        dx = handle_start_x - center_x
        dy = handle_start_y - center_y
        radius = math.hypot(dx, dy)
        delta = math.radians(ticks * sensitivity * 4.0)
        if radius < CENTER_HANDLE_RADIUS:
            # At zero color strength, orbit rotation selects a hue direction
            # only. Moving Jianying's white handle away from the centre would
            # change the picture, so keep it still and rotate only our outer
            # feedback dot. A later diameter gesture can pull outward along
            # this selected angle.
            start_angle = float(state.get("angle", -math.pi / 2))
            target_angle = start_angle + delta
            target_angle = math.atan2(math.sin(target_angle), math.cos(target_angle))
            path = []
            cursor_distance = 0.0
            used_gain = response_gain
            state.update({
                "handleX": center_x,
                "handleY": center_y,
                "cursorX": center_x,
                "cursorY": center_y,
                "angle": target_angle,
                "radius": 0.0,
                "lastMode": mode,
                "orbitPreview": True,
            })
        else:
            start_angle = math.atan2(dy, dx)
            orbit_radius = float(state.get("orbitRadius", radius)) if state.get("lastMode") == mode else radius
            path, orbit_angles, cursor_distance, applied_delta, duration = _relative_orbit_path(
                start_x,
                start_y,
                radius,
                start_angle,
                delta,
                response_gain,
            )
            used_gain = response_gain
            target_angle = start_angle + applied_delta
            # Keep the intended circle across confirmed visual feedback.
            # Correct radial error gradually, without turning an observation
            # into an abrupt jump or permanently shrinking the next circle.
            correction_budget = min(.25, max(0, MAX_CURSOR_DISTANCE_PER_EVENT - cursor_distance) * response_gain)
            correction = (_clamp(orbit_radius - radius, -correction_budget, correction_budget)
                          if path and state.get("orbitCorrectionAllowed", True) else 0.0)
            if correction:
                path = [
                    (x + math.cos(a) * correction * i / len(path) / response_gain,
                     y + math.sin(a) * correction * i / len(path) / response_gain)
                    for i, ((x, y), a) in enumerate(zip(path, orbit_angles), 1)
                ]
                cursor_distance += abs(correction) / response_gain
                radius += correction
            target_x = center_x + math.cos(target_angle) * radius
            target_y = center_y + math.sin(target_angle) * radius
            target_angle = math.atan2(math.sin(target_angle), math.cos(target_angle))
            state.update({
                "handleX": target_x,
                "handleY": target_y,
                "angle": target_angle,
                "radius": radius,
                "lastMode": mode,
                "orbitPreview": False,
                "orbitRadius": orbit_radius,
            })
    else:
        state.pop("orbitPreview", None)
        state.pop("orbitRadius", None)
        dx = handle_start_x - center_x
        dy = handle_start_y - center_y
        radius = math.hypot(dx, dy)
        if state.get("lastMode") != mode or "axisAngle" not in state:
            axis_angle, signed_radius = _diameter_axis(dx, dy, radius)
        else:
            axis_angle = float(state["axisAngle"])
            signed_radius = float(state.get("signedRadius", radius))
        desired_signed_radius = _bounded_signed_radius(
            signed_radius,
            ticks * sensitivity * 1.8,
            safe_radius,
        )
        desired_x = center_x + math.cos(axis_angle) * desired_signed_radius
        desired_y = center_y + math.sin(axis_angle) * desired_signed_radius
        path, applied_dx, applied_dy, cursor_distance, used_gain = _relative_drag_path(
            start_x,
            start_y,
            desired_x - handle_start_x,
            desired_y - handle_start_y,
            response_gain,
        )
        target_x = handle_start_x + applied_dx
        target_y = handle_start_y + applied_dy
        signed_radius = (
            (target_x - center_x) * math.cos(axis_angle)
            + (target_y - center_y) * math.sin(axis_angle)
        )
        display_angle = axis_angle if signed_radius >= 0 else axis_angle + math.pi
        state.update({
            "handleX": target_x,
            "handleY": target_y,
            "angle": display_angle,
            "radius": abs(signed_radius),
            "axisAngle": axis_angle,
            "signedRadius": signed_radius,
            "lastMode": mode,
        })

    if path:
        state["cursorX"], state["cursorY"] = path[-1]
    state["responseGain"] = used_gain

    return {
        "startX": start_x,
        "startY": start_y,
        "path": path,
        "state": state,
        "cursorDistance": cursor_distance,
        "responseGain": used_gain,
        "previewOnly": bool(state.get("orbitPreview")),
        "duration": duration,
        "orbitAngles": orbit_angles,
    }


def resume_diameter_state(target, state):
    """Rebase a paused diameter gesture onto the reacquired white handle."""
    resumes_diameter = bool(
        isinstance(state, dict)
        and state.get("lastMode") == "diameter"
        and state.get("axisAngle") is not None
    )
    resumes_orbit_preview = bool(
        isinstance(state, dict)
        and state.get("lastMode") == "orbit"
        and state.get("orbitPreview") is True
        and state.get("angle") is not None
    )
    if (
        not isinstance(state, dict)
        or state.get("signature") != _geometry_signature(target)
        or not (resumes_diameter or resumes_orbit_preview)
    ):
        return None

    resumed = dict(state)
    fresh = _initial_state(target)
    try:
        previous_handle_x = float(state["handleX"])
        previous_handle_y = float(state["handleY"])
    except (KeyError, TypeError, ValueError):
        return None
    reacquire_drift = math.hypot(
        fresh["handleX"] - previous_handle_x,
        fresh["handleY"] - previous_handle_y,
    )
    max_reacquire_drift = max(4.0, min(8.0, fresh["wheelRadius"] * 0.12))
    if reacquire_drift > max_reacquire_drift:
        return None
    fresh_radius = math.hypot(
        fresh["handleX"] - fresh["centerX"],
        fresh["handleY"] - fresh["centerY"],
    )
    if resumes_orbit_preview and fresh_radius >= CENTER_HANDLE_RADIUS:
        return None
    axis_angle = float(
        state["angle"] if resumes_orbit_preview else state["axisAngle"]
    )
    dx = fresh["handleX"] - fresh["centerX"]
    dy = fresh["handleY"] - fresh["centerY"]
    signed_radius = dx * math.cos(axis_angle) + dy * math.sin(axis_angle)
    resumed.update({
        "signature": fresh["signature"],
        "centerX": fresh["centerX"],
        "centerY": fresh["centerY"],
        "wheelRadius": fresh["wheelRadius"],
        "safeRadius": fresh["safeRadius"],
        "handleX": fresh["handleX"],
        "handleY": fresh["handleY"],
        # A new mouse-down must begin on the reacquired white point, while the
        # remembered diameter determines where subsequent rotation moves it.
        "cursorX": fresh["handleX"],
        "cursorY": fresh["handleY"],
        "axisAngle": axis_angle,
        "signedRadius": signed_radius,
        "radius": abs(signed_radius),
        "angle": axis_angle if signed_radius >= 0 else axis_angle + math.pi,
        "lastMode": "diameter",
    })
    resumed.pop("orbitPreview", None)
    return resumed


def centered_wheel_state(target, preserve_vertical_axis=False):
    state = _initial_state(target)
    state.update({
        "handleX": state["centerX"],
        "handleY": state["centerY"],
        "cursorX": state["centerX"],
        "cursorY": state["centerY"],
        "radius": 0.0,
        "angle": -math.pi / 2,
        "lastMode": "",
    })
    if preserve_vertical_axis:
        # A macOS reset establishes an exact diameter across ROI reacquisition;
        # a noisy white centroid must not define a new direction at the centre.
        state.update(lastMode="diameter", axisAngle=-math.pi / 2, signedRadius=0.0)
    return state


def resume_orbit_state(target, state):
    """Keep a circle across an idle release, but respect manual relocation."""
    if (not isinstance(state, dict) or state.get("lastMode") != "orbit"
            or state.get("orbitPreview")
            or state.get("signature") != _geometry_signature(target)):
        return None
    fresh = _initial_state(target)
    drift = math.hypot(fresh["handleX"] - state["handleX"], fresh["handleY"] - state["handleY"])
    if drift > max(4.0, min(8.0, fresh["wheelRadius"] * .12)):
        return None
    fresh.update(lastMode="orbit", orbitRadius=state.get("orbitRadius", state["radius"]),
                 orbitCorrectionAllowed=state.get("orbitCorrectionAllowed", True))
    return fresh


__all__ = [
    "VALID_WHEEL_MODES",
    "DEFAULT_RESPONSE_GAIN",
    "MAX_DIAMETER_RADIUS_RATIO",
    "MAX_RESPONSE_GAIN",
    "MIN_RESPONSE_GAIN",
    "centered_wheel_state",
    "normalize_wheel_mode",
    "plan_wheel_motion",
    "resume_diameter_state",
    "resume_orbit_state",
]
