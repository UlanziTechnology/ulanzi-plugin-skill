"""One-shot, hover-selected Resolve color-wheel recognition.

This module is deliberately self-contained inside the wheel lab.  It borrows
the *algorithmic shape* of the production plugin's detector (saturated-wheel
component, crosshair refinement, then neutral handle), but it does not import
the neighbouring production plugin at runtime.  All pixel-to-screen mapping is
performed through :class:`~davinci.smooth_wheel.macos.CapturedBitmap`, including Retina
captures and non-default CoreGraphics channel layouts.

``recognize_hovered_wheel`` is synchronous by design and must be called only at
an explicit setup boundary such as Arm.  It performs exactly one in-memory
screen capture and contains no sleeps, retries, mouse movement, or 120 Hz
gesture-loop work.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .macos import CapturedBitmap, DAVINCI_BUNDLE_ID
from .passive_observer import detect_neutral_handle


Point = Tuple[float, float]

DEFAULT_SEARCH_HALF_SIZE = 240.0
MIN_SEARCH_HALF_SIZE = 64.0
MAX_SEARCH_HALF_SIZE = 512.0

WHEEL_SAMPLE_LOGICAL_STEP = 2.0
WHEEL_COLOR_BRIGHTNESS_MIN = 70
WHEEL_COLOR_SATURATION_MIN = 55
WHEEL_COMPONENT_MIN_SAMPLES = 32
WHEEL_MIN_DIAMETER = 36.0
WHEEL_MAX_DIAMETER = 280.0
WHEEL_MIN_SQUARE_RATIO = 0.60
WHEEL_MIN_ANGULAR_COVERAGE = 0.58
WHEEL_ANGLE_BINS = 24
WHEEL_TRIM_FRACTION = 0.02

CROSSHAIR_SEARCH_RADIUS_RATIO = 0.34
CROSSHAIR_LINE_RADIUS_RATIO = 0.68
CROSSHAIR_MIN_SCORE = 0.16
CROSSHAIR_MAX_CHANNEL_SPREAD = 52
CROSSHAIR_MIN_LUMA = 68.0

MAX_BITMAP_PIXEL_SIDE = 2048
MAX_BITMAP_PIXEL_AREA = 2048 * 2048
MIN_HANDLE_CONFIDENCE = 0.45


@dataclass(frozen=True)
class WheelCalibration:
    """Screen-space calibration produced by one successful recognition."""

    center: Point
    handle: Point
    visual_radius: float
    rim: Point
    confidence: float
    geometry_confidence: float
    handle_confidence: float

    def to_dict(self) -> dict:
        return {
            "center": {"x": self.center[0], "y": self.center[1]},
            "handle": {"x": self.handle[0], "y": self.handle[1]},
            "visualRadius": self.visual_radius,
            "rim": {"x": self.rim[0], "y": self.rim[1]},
            "confidence": self.confidence,
            "geometryConfidence": self.geometry_confidence,
            "handleConfidence": self.handle_confidence,
            "source": "hover-one-shot",
        }


@dataclass(frozen=True)
class WheelRecognitionResult:
    """Fail-closed recognition result with stable machine-readable reasons."""

    status: str
    reason: str
    calibration: Optional[WheelCalibration] = None
    detail: str = ""
    diagnostics: Optional[Mapping[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.status == "ready" and self.calibration is not None

    def to_dict(self) -> dict:
        result = {
            "status": self.status,
            "result": self.status,
            "reason": self.reason,
            "ok": self.ok,
            "diagnostics": dict(self.diagnostics or {}),
        }
        if self.detail:
            result["detail"] = self.detail
        if self.calibration is not None:
            result["calibration"] = self.calibration.to_dict()
        return result


def _failed(
    reason: str,
    detail: str = "",
    diagnostics: Optional[Mapping[str, Any]] = None,
) -> WheelRecognitionResult:
    return WheelRecognitionResult(
        status="failed",
        reason=str(reason),
        detail=str(detail or ""),
        diagnostics=dict(diagnostics or {}),
    )


def _ready(
    calibration: WheelCalibration,
    diagnostics: Optional[Mapping[str, Any]] = None,
) -> WheelRecognitionResult:
    return WheelRecognitionResult(
        status="ready",
        reason="recognized",
        calibration=calibration,
        diagnostics=dict(diagnostics or {}),
    )


def _point(value: Any) -> Optional[Point]:
    if isinstance(value, Mapping):
        raw = (value.get("x"), value.get("y"))
    else:
        try:
            raw = (value[0], value[1])
        except (IndexError, KeyError, TypeError):
            return None
    try:
        point = (float(raw[0]), float(raw[1]))
    except (TypeError, ValueError):
        return None
    return point if all(math.isfinite(item) for item in point) else None


def _validate_bitmap(bitmap: Any) -> Optional[str]:
    if not isinstance(bitmap, CapturedBitmap):
        return "capture did not return CapturedBitmap"
    if bitmap.width <= 0 or bitmap.height <= 0:
        return "capture dimensions are empty"
    if (
        bitmap.width > MAX_BITMAP_PIXEL_SIDE
        or bitmap.height > MAX_BITMAP_PIXEL_SIDE
        or bitmap.width * bitmap.height > MAX_BITMAP_PIXEL_AREA
    ):
        return "capture exceeds recognition bitmap limits"
    if bitmap.bytes_per_row < bitmap.width * 4:
        return "capture row stride is invalid"
    if len(bitmap.pixels) < bitmap.bytes_per_row * bitmap.height:
        return "capture pixel buffer is incomplete"
    if (
        not math.isfinite(bitmap.scale_x)
        or not math.isfinite(bitmap.scale_y)
        or bitmap.scale_x <= 0.0
        or bitmap.scale_y <= 0.0
    ):
        return "capture scale is invalid"
    try:
        offsets = tuple(int(item) for item in bitmap.color_offsets)
    except (TypeError, ValueError):
        return "capture color offsets are invalid"
    if (
        len(offsets) != 3
        or len(set(offsets)) != 3
        or any(item < 0 or item > 3 for item in offsets)
    ):
        return "capture color offsets are invalid"
    rect = tuple(bitmap.screen_rect)
    if len(rect) != 4:
        return "capture screen rectangle is invalid"
    try:
        left, top, width, height = (float(item) for item in rect)
    except (TypeError, ValueError):
        return "capture screen rectangle is invalid"
    if (
        not all(math.isfinite(item) for item in (left, top, width, height))
        or width <= 0.0
        or height <= 0.0
    ):
        return "capture screen rectangle is invalid"
    return None


def _rgb_at(bitmap: CapturedBitmap, pixel_x: int, pixel_y: int) -> Optional[Tuple[int, int, int]]:
    if pixel_x < 0 or pixel_y < 0 or pixel_x >= bitmap.width or pixel_y >= bitmap.height:
        return None
    offset = pixel_y * bitmap.bytes_per_row + pixel_x * 4
    red_offset, green_offset, blue_offset = bitmap.color_offsets
    return (
        bitmap.pixels[offset + red_offset],
        bitmap.pixels[offset + green_offset],
        bitmap.pixels[offset + blue_offset],
    )


def _screen_point(bitmap: CapturedBitmap, pixel_x: float, pixel_y: float) -> Point:
    left, top, _width, _height = bitmap.screen_rect
    return (
        float(left) + pixel_x / bitmap.scale_x,
        float(top) + pixel_y / bitmap.scale_y,
    )


def _pixel_point(bitmap: CapturedBitmap, screen_x: float, screen_y: float) -> Point:
    left, top, _width, _height = bitmap.screen_rect
    return (
        (screen_x - float(left)) * bitmap.scale_x,
        (screen_y - float(top)) * bitmap.scale_y,
    )


def _is_wheel_color(color: Optional[Sequence[int]]) -> bool:
    if not color:
        return False
    return (
        max(color) >= WHEEL_COLOR_BRIGHTNESS_MIN
        and max(color) - min(color) >= WHEEL_COLOR_SATURATION_MIN
    )


def _trimmed_bounds(values: Iterable[float]) -> Optional[Tuple[float, float]]:
    ordered = sorted(float(item) for item in values)
    if not ordered:
        return None
    trim_count = int(len(ordered) * WHEEL_TRIM_FRACTION)
    if trim_count * 2 >= len(ordered):
        trim_count = 0
    return ordered[trim_count], ordered[len(ordered) - trim_count - 1]


def _percentile(values: Iterable[float], fraction: float) -> Optional[float]:
    ordered = sorted(float(item) for item in values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
    return ordered[index]


def _luma(color: Optional[Sequence[int]]) -> float:
    if not color:
        return 0.0
    return 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]


def _crosshair_strength(
    bitmap: CapturedBitmap,
    pixel_x: int,
    pixel_y: int,
    orientation: str,
) -> float:
    color = _rgb_at(bitmap, pixel_x, pixel_y)
    if not color:
        return 0.0
    spread = max(color) - min(color)
    luma = _luma(color)
    if spread > CROSSHAIR_MAX_CHANNEL_SPREAD or luma < CROSSHAIR_MIN_LUMA:
        return 0.0

    scale = bitmap.scale_y if orientation == "horizontal" else bitmap.scale_x
    neighbour_offset = max(2, int(round(3.0 * scale)))
    neighbour_lumas = []
    for delta in (-neighbour_offset, neighbour_offset):
        if orientation == "horizontal":
            neighbour = _rgb_at(bitmap, pixel_x, pixel_y + delta)
        else:
            neighbour = _rgb_at(bitmap, pixel_x + delta, pixel_y)
        if neighbour is not None:
            neighbour_lumas.append(_luma(neighbour))
    contrast = luma - sum(neighbour_lumas) / len(neighbour_lumas) if neighbour_lumas else 0.0
    if contrast < 4.0 and luma < 115.0:
        return 0.0
    neutral_score = (CROSSHAIR_MAX_CHANNEL_SPREAD - spread) / CROSSHAIR_MAX_CHANNEL_SPREAD
    contrast_score = max(0.0, min(contrast, 55.0)) / 55.0
    brightness_score = max(0.0, min(luma - CROSSHAIR_MIN_LUMA, 100.0)) / 100.0
    return 0.55 + neutral_score * 0.65 + contrast_score * 0.75 + brightness_score * 0.25


def _score_crosshair_line(
    bitmap: CapturedBitmap,
    orientation: str,
    position: int,
    center_pixel_x: float,
    center_pixel_y: float,
    logical_line_radius: float,
) -> Tuple[float, int]:
    total = 0.0
    count = 0
    if orientation == "horizontal":
        if position < 0 or position >= bitmap.height:
            return 0.0, 0
        radius = logical_line_radius * bitmap.scale_x
        start = max(0, int(round(center_pixel_x - radius)))
        end = min(bitmap.width - 1, int(round(center_pixel_x + radius)))
        for pixel_x in range(start, end + 1):
            total += _crosshair_strength(bitmap, pixel_x, position, orientation)
            count += 1
    else:
        if position < 0 or position >= bitmap.width:
            return 0.0, 0
        radius = logical_line_radius * bitmap.scale_y
        start = max(0, int(round(center_pixel_y - radius)))
        end = min(bitmap.height - 1, int(round(center_pixel_y + radius)))
        for pixel_y in range(start, end + 1):
            total += _crosshair_strength(bitmap, position, pixel_y, orientation)
            count += 1
    return total / max(1, count), count


def _weighted_crosshair_peak(candidates: List[dict], scale: float) -> Optional[dict]:
    if not candidates:
        return None
    best = max(candidates, key=lambda item: item["score"])
    if best["score"] < CROSSHAIR_MIN_SCORE:
        return None
    pixel_tolerance = max(1.0, 3.0 * scale)
    threshold = max(CROSSHAIR_MIN_SCORE, best["score"] * 0.72)
    peak = [
        candidate
        for candidate in candidates
        if abs(candidate["position"] - best["position"]) <= pixel_tolerance
        and candidate["score"] >= threshold
    ]
    total = sum(candidate["score"] for candidate in peak)
    if total <= 0.0:
        return best
    return {
        "position": sum(candidate["position"] * candidate["score"] for candidate in peak)
        / total,
        "score": best["score"],
        "samples": best["samples"],
    }


def _refine_crosshair_center(
    bitmap: CapturedBitmap,
    rough_center: Point,
    rough_radius: float,
) -> Optional[dict]:
    if rough_radius < 18.0:
        return None
    center_pixel_x, center_pixel_y = _pixel_point(bitmap, *rough_center)
    search_radius = max(6.0, rough_radius * CROSSHAIR_SEARCH_RADIUS_RATIO)
    line_radius = max(14.0, rough_radius * CROSSHAIR_LINE_RADIUS_RATIO)

    row_candidates = []
    row_start = max(0, int(round(center_pixel_y - search_radius * bitmap.scale_y)))
    row_end = min(bitmap.height - 1, int(round(center_pixel_y + search_radius * bitmap.scale_y)))
    for pixel_y in range(row_start, row_end + 1):
        score, samples = _score_crosshair_line(
            bitmap,
            "horizontal",
            pixel_y,
            center_pixel_x,
            center_pixel_y,
            line_radius,
        )
        row_candidates.append({"position": pixel_y, "score": score, "samples": samples})

    column_candidates = []
    column_start = max(0, int(round(center_pixel_x - search_radius * bitmap.scale_x)))
    column_end = min(bitmap.width - 1, int(round(center_pixel_x + search_radius * bitmap.scale_x)))
    for pixel_x in range(column_start, column_end + 1):
        score, samples = _score_crosshair_line(
            bitmap,
            "vertical",
            pixel_x,
            center_pixel_x,
            center_pixel_y,
            line_radius,
        )
        column_candidates.append({"position": pixel_x, "score": score, "samples": samples})

    row_peak = _weighted_crosshair_peak(row_candidates, bitmap.scale_y)
    column_peak = _weighted_crosshair_peak(column_candidates, bitmap.scale_x)
    if row_peak is None or column_peak is None:
        return None
    center = _screen_point(bitmap, column_peak["position"] + 0.5, row_peak["position"] + 0.5)
    return {
        "center": center,
        "horizontalScore": row_peak["score"],
        "verticalScore": column_peak["score"],
    }


def _angular_coverage(points: Sequence[Point], center: Point, radius: float) -> float:
    if radius <= 0.0:
        return 0.0
    bins = set()
    minimum_radius = radius * 0.55
    for point_x, point_y in points:
        delta_x = point_x - center[0]
        delta_y = point_y - center[1]
        if math.hypot(delta_x, delta_y) < minimum_radius:
            continue
        angle = math.atan2(delta_y, delta_x) % (math.pi * 2.0)
        bins.add(min(WHEEL_ANGLE_BINS - 1, int(angle / (math.pi * 2.0) * WHEEL_ANGLE_BINS)))
    return len(bins) / WHEEL_ANGLE_BINS


def _wheel_components(bitmap: CapturedBitmap) -> List[dict]:
    border_x = max(1, int(round(4.0 * bitmap.scale_x)))
    border_y = max(1, int(round(4.0 * bitmap.scale_y)))
    step_x = max(1, int(round(WHEEL_SAMPLE_LOGICAL_STEP * bitmap.scale_x)))
    step_y = max(1, int(round(WHEEL_SAMPLE_LOGICAL_STEP * bitmap.scale_y)))
    pixel_xs = list(range(border_x, max(border_x, bitmap.width - border_x), step_x))
    pixel_ys = list(range(border_y, max(border_y, bitmap.height - border_y), step_y))
    sampled: Dict[Tuple[int, int], Point] = {}
    for grid_y, pixel_y in enumerate(pixel_ys):
        for grid_x, pixel_x in enumerate(pixel_xs):
            if _is_wheel_color(_rgb_at(bitmap, pixel_x, pixel_y)):
                sampled[(grid_x, grid_y)] = _screen_point(bitmap, pixel_x + 0.5, pixel_y + 0.5)

    components = []
    remaining = dict(sampled)
    while remaining:
        seed = next(iter(remaining))
        pending = [seed]
        points = [remaining.pop(seed)]
        while pending:
            grid_x, grid_y = pending.pop()
            for neighbour_y in range(grid_y - 1, grid_y + 2):
                for neighbour_x in range(grid_x - 1, grid_x + 2):
                    neighbour = (neighbour_x, neighbour_y)
                    point = remaining.pop(neighbour, None)
                    if point is not None:
                        pending.append(neighbour)
                        points.append(point)
        if len(points) < WHEEL_COMPONENT_MIN_SAMPLES:
            continue

        x_bounds = _trimmed_bounds(point[0] for point in points)
        y_bounds = _trimmed_bounds(point[1] for point in points)
        if x_bounds is None or y_bounds is None:
            continue
        minimum_x, maximum_x = x_bounds
        minimum_y, maximum_y = y_bounds
        width = maximum_x - minimum_x
        height = maximum_y - minimum_y
        smaller = min(width, height)
        larger = max(width, height)
        if smaller < WHEEL_MIN_DIAMETER or larger > WHEEL_MAX_DIAMETER:
            continue
        square_ratio = smaller / max(1.0, larger)
        if square_ratio < WHEEL_MIN_SQUARE_RATIO:
            continue
        rough_center = ((minimum_x + maximum_x) / 2.0, (minimum_y + maximum_y) / 2.0)
        rough_radius = larger / 2.0
        coverage = _angular_coverage(points, rough_center, rough_radius)
        if coverage < WHEEL_MIN_ANGULAR_COVERAGE:
            continue

        crosshair = _refine_crosshair_center(bitmap, rough_center, rough_radius)
        center = crosshair["center"] if crosshair else rough_center
        radius_from_points = _percentile(
            (math.hypot(point[0] - center[0], point[1] - center[1]) for point in points),
            0.98,
        )
        visual_radius = max(rough_radius, float(radius_from_points or 0.0))
        if visual_radius < WHEEL_MIN_DIAMETER / 2.0 or visual_radius > WHEEL_MAX_DIAMETER / 2.0:
            continue

        crosshair_score = 0.0
        if crosshair:
            crosshair_score = min(
                1.0,
                (crosshair["horizontalScore"] + crosshair["verticalScore"]) / 1.5,
            )
        geometry_confidence = max(
            0.0,
            min(
                1.0,
                0.28
                + square_ratio * 0.28
                + coverage * 0.24
                + crosshair_score * 0.20,
            ),
        )
        components.append({
            "center": center,
            "roughCenter": rough_center,
            "visualRadius": visual_radius,
            "geometryConfidence": geometry_confidence,
            "squareRatio": square_ratio,
            "angularCoverage": coverage,
            "sampleCount": len(points),
            "crosshair": crosshair,
            "bounds": {
                "left": minimum_x,
                "top": minimum_y,
                "width": width,
                "height": height,
            },
        })
    return components


def _crop_bitmap(bitmap: CapturedBitmap, center: Point, half_size: float) -> CapturedBitmap:
    center_pixel_x, center_pixel_y = _pixel_point(bitmap, *center)
    pixel_half_width = half_size * bitmap.scale_x
    pixel_half_height = half_size * bitmap.scale_y
    minimum_x = max(0, int(math.floor(center_pixel_x - pixel_half_width)))
    maximum_x = min(bitmap.width, int(math.ceil(center_pixel_x + pixel_half_width)))
    minimum_y = max(0, int(math.floor(center_pixel_y - pixel_half_height)))
    maximum_y = min(bitmap.height, int(math.ceil(center_pixel_y + pixel_half_height)))
    width = max(0, maximum_x - minimum_x)
    height = max(0, maximum_y - minimum_y)
    bytes_per_row = width * 4
    rows = []
    for pixel_y in range(minimum_y, maximum_y):
        start = pixel_y * bitmap.bytes_per_row + minimum_x * 4
        rows.append(bitmap.pixels[start : start + bytes_per_row])
    screen_left, screen_top = _screen_point(bitmap, minimum_x, minimum_y)
    return CapturedBitmap(
        pixels=b"".join(rows),
        width=width,
        height=height,
        bytes_per_row=bytes_per_row,
        screen_rect=(
            screen_left,
            screen_top,
            width / bitmap.scale_x,
            height / bitmap.scale_y,
        ),
        scale_x=bitmap.scale_x,
        scale_y=bitmap.scale_y,
        color_offsets=bitmap.color_offsets,
    )


def detect_hovered_wheel(
    bitmap: CapturedBitmap,
    hover_point: Any,
    *,
    expected_handle: Any = None,
) -> WheelRecognitionResult:
    """Recognize the color wheel underneath ``hover_point`` in one bitmap.

    This is the pure/testable half of the API.  It never captures the screen,
    checks permissions, moves the pointer, or waits.
    """

    invalid_bitmap = _validate_bitmap(bitmap)
    if invalid_bitmap:
        return _failed("invalid_capture", invalid_bitmap)
    hover = _point(hover_point)
    if hover is None:
        return _failed("invalid_hover_point")

    candidates = _wheel_components(bitmap)
    diagnostics: Dict[str, Any] = {
        "candidateCount": len(candidates),
        "hover": {"x": hover[0], "y": hover[1]},
        "captureScale": {"x": bitmap.scale_x, "y": bitmap.scale_y},
    }
    if not candidates:
        return _failed("no_wheel_candidate", diagnostics=diagnostics)

    hovered = []
    for candidate in candidates:
        center = candidate["center"]
        radius = candidate["visualRadius"]
        distance = math.hypot(hover[0] - center[0], hover[1] - center[1])
        hit_padding = max(5.0, radius * 0.08)
        if distance <= radius + hit_padding:
            item = dict(candidate)
            item["hoverDistance"] = distance
            item["normalizedHoverDistance"] = distance / max(1.0, radius)
            hovered.append(item)
    if not hovered:
        diagnostics["candidateCenters"] = [
            {
                "x": item["center"][0],
                "y": item["center"][1],
                "radius": item["visualRadius"],
            }
            for item in candidates
        ]
        return _failed("no_hovered_wheel_candidate", diagnostics=diagnostics)

    hovered.sort(
        key=lambda item: (
            item["normalizedHoverDistance"],
            -item["geometryConfidence"],
        )
    )
    selected = hovered[0]
    center = selected["center"]
    visual_radius = selected["visualRadius"]
    diagnostics.update({
        "hoveredCandidateCount": len(hovered),
        "selected": {
            "center": {"x": center[0], "y": center[1]},
            "visualRadius": visual_radius,
            "geometryConfidence": selected["geometryConfidence"],
            "hoverDistance": selected["hoverDistance"],
            "squareRatio": selected["squareRatio"],
            "angularCoverage": selected["angularCoverage"],
            "sampleCount": selected["sampleCount"],
            "crosshairDetected": selected["crosshair"] is not None,
        },
    })

    expected = _point(expected_handle)
    handle_bitmap = _crop_bitmap(bitmap, center, visual_radius + max(8.0, visual_radius * 0.12))
    detected_handle = detect_neutral_handle(
        handle_bitmap,
        center,
        visual_radius,
        expected,
    )
    if detected_handle is None:
        return _failed("white_handle_not_detected", diagnostics=diagnostics)
    handle_confidence = float(detected_handle.get("confidence") or 0.0)
    diagnostics["handle"] = dict(detected_handle)
    if handle_confidence < MIN_HANDLE_CONFIDENCE:
        return _failed("white_handle_ambiguous", diagnostics=diagnostics)
    handle_position = detected_handle.get("position") or {}
    handle = _point(handle_position)
    if handle is None:
        return _failed("white_handle_invalid", diagnostics=diagnostics)

    delta_x = handle[0] - center[0]
    delta_y = handle[1] - center[1]
    handle_radius = math.hypot(delta_x, delta_y)
    if handle_radius <= 1e-6:
        rim = (center[0] + visual_radius, center[1])
    else:
        rim = (
            center[0] + delta_x / handle_radius * visual_radius,
            center[1] + delta_y / handle_radius * visual_radius,
        )
    geometry_confidence = float(selected["geometryConfidence"])
    confidence = max(0.0, min(1.0, geometry_confidence * 0.55 + handle_confidence * 0.45))
    calibration = WheelCalibration(
        center=center,
        handle=handle,
        visual_radius=visual_radius,
        rim=rim,
        confidence=confidence,
        geometry_confidence=geometry_confidence,
        handle_confidence=handle_confidence,
    )
    return _ready(calibration, diagnostics)


def _result_with_diagnostics(
    result: WheelRecognitionResult,
    diagnostics: Mapping[str, Any],
) -> WheelRecognitionResult:
    merged = dict(result.diagnostics or {})
    merged.update(diagnostics)
    return WheelRecognitionResult(
        status=result.status,
        reason=result.reason,
        calibration=result.calibration,
        detail=result.detail,
        diagnostics=merged,
    )


def recognize_hovered_wheel(
    bindings: Any,
    hover_point: Any = None,
    *,
    expected_handle: Any = None,
    search_half_size: float = DEFAULT_SEARCH_HALF_SIZE,
    clock: Any = time.monotonic,
) -> WheelRecognitionResult:
    """Perform one fail-closed recognition using exactly one screen capture.

    Stable failure reasons include ``platform_unavailable``,
    ``davinci_not_frontmost``, ``screen_capture_unavailable``,
    ``screen_capture_permission_unavailable``, ``screen_capture_failed``,
    ``no_wheel_candidate``, ``no_hovered_wheel_candidate``, and
    ``white_handle_not_detected``.
    """

    started_at = clock()
    if bindings is None or getattr(bindings, "available", True) is False:
        return _failed(
            "platform_unavailable",
            str(getattr(bindings, "unavailable_reason", "") or "macOS bindings are unavailable"),
        )

    try:
        app = bindings.frontmost_app()
    except Exception as exc:
        return _failed("frontmost_check_failed", str(exc))
    is_davinci = bool(getattr(app, "is_davinci", False))
    if not is_davinci:
        is_davinci = (
            getattr(app, "bundle_id", "") == DAVINCI_BUNDLE_ID
            and getattr(app, "pid", None) is not None
        )
    if not is_davinci:
        return _failed(
            "davinci_not_frontmost",
            diagnostics={"frontmostBundleId": str(getattr(app, "bundle_id", "") or "")},
        )

    supported = getattr(bindings, "screen_capture_supported", None)
    if callable(supported):
        try:
            if not supported():
                return _failed("screen_capture_unavailable")
        except Exception as exc:
            return _failed("screen_capture_support_check_failed", str(exc))
    if not callable(getattr(bindings, "capture_screen_region", None)):
        return _failed("screen_capture_unavailable")

    allowed = getattr(bindings, "screen_capture_allowed", None)
    if not callable(allowed):
        return _failed("screen_capture_permission_check_unavailable")
    try:
        if not allowed():
            return _failed("screen_capture_permission_unavailable")
    except Exception as exc:
        return _failed("screen_capture_permission_check_failed", str(exc))

    hover = _point(hover_point)
    if hover_point is None:
        try:
            hover = _point(bindings.current_mouse_position())
        except Exception as exc:
            return _failed("hover_point_unavailable", str(exc))
    if hover is None:
        return _failed("invalid_hover_point")

    try:
        half_size = float(search_half_size)
    except (TypeError, ValueError):
        return _failed("invalid_search_window")
    if (
        not math.isfinite(half_size)
        or half_size < MIN_SEARCH_HALF_SIZE
        or half_size > MAX_SEARCH_HALF_SIZE
    ):
        return _failed("invalid_search_window")

    try:
        display = tuple(float(item) for item in bindings.display_bounds_for_point(hover))
        if len(display) != 4:
            raise ValueError("display rectangle must have four values")
        display_left, display_top, display_width, display_height = display
        if (
            not all(math.isfinite(item) for item in display)
            or display_width <= 0.0
            or display_height <= 0.0
        ):
            raise ValueError("display rectangle is invalid")
    except Exception as exc:
        return _failed("display_bounds_unavailable", str(exc))

    left = max(display_left, math.floor(hover[0] - half_size))
    top = max(display_top, math.floor(hover[1] - half_size))
    right = min(display_left + display_width, math.ceil(hover[0] + half_size))
    bottom = min(display_top + display_height, math.ceil(hover[1] + half_size))
    roi = (left, top, right - left, bottom - top)
    if roi[2] < WHEEL_MIN_DIAMETER or roi[3] < WHEEL_MIN_DIAMETER:
        return _failed("search_window_outside_display")

    capture_started = clock()
    try:
        bitmap = bindings.capture_screen_region(*roi)
    except Exception as exc:
        return _failed(
            "screen_capture_failed",
            str(exc),
            diagnostics={"roi": {"x": roi[0], "y": roi[1], "w": roi[2], "h": roi[3]}},
        )
    capture_finished = clock()
    result = detect_hovered_wheel(bitmap, hover, expected_handle=expected_handle)
    finished_at = clock()
    return _result_with_diagnostics(result, {
        "roi": {"x": roi[0], "y": roi[1], "w": roi[2], "h": roi[3]},
        "captureMs": max(0.0, (capture_finished - capture_started) * 1000.0),
        "detectMs": max(0.0, (finished_at - capture_finished) * 1000.0),
        "totalMs": max(0.0, (finished_at - started_at) * 1000.0),
        "captureCount": 1,
    })


__all__ = [
    "WheelCalibration",
    "WheelRecognitionResult",
    "detect_hovered_wheel",
    "recognize_hovered_wheel",
]
