"""Runtime adapter for pixel-based wheel detection helpers."""

from .wheel_confirmed_geometry import confirmed_geometry_for_area

from .wheel_detection import (
    detect_horizontal_slider_track_in_region,
    detect_vertical_slider_handle_in_area,
    detect_vertical_slider_tracks_in_region,
    detect_wheel_circle_geometry,
    detect_wheel_handle_in_region,
)


class WheelDetectionAdapter:
    def __init__(self, capture_screen_region_fn, debug_slow_fn=None):
        self.capture_screen_region_fn = capture_screen_region_fn
        self.debug_slow_fn = debug_slow_fn

    def detect_wheel_circle_in_area(self, area):
        confirmed = confirmed_geometry_for_area(area)
        if confirmed is not None:
            return confirmed
        return detect_wheel_circle_geometry(
            area,
            self.capture_screen_region_fn,
            self.debug_slow_fn,
        )

    def detect_handle_in_area(
        self,
        area_x,
        area_y,
        area_w,
        area_h=None,
        wheel_geometry=None,
        expected_handle=None,
        expected_axis=None,
    ):
        return detect_wheel_handle_in_region(
            area_x,
            area_y,
            area_w,
            capture_screen_region_fn=self.capture_screen_region_fn,
            area_h=area_h,
            wheel_geometry=wheel_geometry,
            expected_handle=expected_handle,
            expected_axis=expected_axis,
        )

    def detect_vertical_slider_handle(self, area):
        return detect_vertical_slider_handle_in_area(area, self.capture_screen_region_fn)

    def detect_vertical_slider_tracks(self, search_rect):
        return detect_vertical_slider_tracks_in_region(search_rect, self.capture_screen_region_fn)

    def detect_horizontal_slider_track(self, search_rect):
        return detect_horizontal_slider_track_in_region(search_rect, self.capture_screen_region_fn)


__all__ = ['WheelDetectionAdapter']
