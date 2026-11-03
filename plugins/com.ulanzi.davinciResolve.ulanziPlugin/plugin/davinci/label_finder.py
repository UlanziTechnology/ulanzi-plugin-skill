"""Injected LabelFinder class for DaVinci UI discovery."""

from functools import partial

from .label_area_assembler import calculate_wheel_target_areas
from .label_app_state import (
    find_davinci_app as label_find_davinci_app,
    initialize_ax as label_initialize_ax,
    is_app_running as label_is_app_running,
    is_frontmost as label_is_frontmost,
    refresh_main_window as label_refresh_main_window,
)
from .label_color_page_activation import activate_color_page as label_activate_color_page
from .label_element_access import (
    click_element as access_click_element,
    get_ax_attribute,
    get_element_children as access_get_element_children,
    get_element_frame as access_get_element_frame,
    get_element_role as access_get_element_role,
    get_element_text as access_get_element_text,
    parse_ax_frame_value,
)
from .label_numeric_input_scan import scan_numeric_inputs
from .label_slider_input_scan import scan_vertical_slider_inputs
from .label_text_scan import collect_diagnostic_texts, find_first_text as scan_first_text
from .label_wheel_label_scan import scan_wheel_labels
from .label_window_matcher import score_davinci_window_info
from .layout_scan_guard import check_layout_scan
from .wheel_confirmed_geometry import WheelGeometryCache, layout_geometry_context


def create_label_finder_class(
    *,
    is_windows,
    win32_available,
    windows_uia_available,
    user32_obj,
    is_mac,
    davinci_available,
    desktop_cls,
    workspace_cls,
    running_application_cls,
    ax_create_application_fn,
    ax_perform_action_fn,
    ax_copy_attribute_value_fn,
    press_action,
    ax_text_attributes,
    win32_window_info,
    platform_mouse_input,
    wheel_detection_adapter,
    debug_slow_fn,
    sleep_fn,
):
    get_attr_fn = partial(
        get_ax_attribute,
        is_mac=is_mac,
        copy_attr_value_fn=ax_copy_attribute_value_fn,
    )

    class LabelFinder:
        """Finds DaVinci Color Wheels labels and target areas."""

        def __init__(self):
            self.ax_app = None
            self.main_win = None
            self.target_app = None
            self.uia_window = None
            self.target_hwnd = 0
            self.target_pid = 0
            self.labels = []
            self._wheel_geometry_cache = WheelGeometryCache()

        def find_davinci_app(self):
            return label_find_davinci_app(
                self,
                is_windows=is_windows,
                win32_available=win32_available,
                windows_uia_available=windows_uia_available,
                user32_obj=user32_obj,
                is_mac=is_mac,
                davinci_available=davinci_available,
                desktop_cls=desktop_cls,
                workspace_cls=workspace_cls,
                running_application_cls=running_application_cls,
                find_windows_by_title_fn=win32_window_info.find_windows_by_title,
                score_window_info_fn=lambda info: score_davinci_window_info(
                    info,
                    win32_window_info.get_window_process_path,
                ),
                get_window_process_id_fn=win32_window_info.get_window_process_id,
            )

        def is_app_running(self):
            return label_is_app_running(
                self,
                is_windows=is_windows,
                win32_available=win32_available,
                user32_obj=user32_obj,
                is_mac=is_mac,
                davinci_available=davinci_available,
                workspace_cls=workspace_cls,
                running_application_cls=running_application_cls,
                get_window_process_id_fn=win32_window_info.get_window_process_id,
            )

        def is_frontmost(self):
            return label_is_frontmost(
                self,
                is_windows=is_windows,
                win32_available=win32_available,
                user32_obj=user32_obj,
                is_mac=is_mac,
                davinci_available=davinci_available,
                workspace_cls=workspace_cls,
                running_application_cls=running_application_cls,
                get_window_process_id_fn=win32_window_info.get_window_process_id,
            )

        def init_ax(self):
            return label_initialize_ax(
                self,
                is_windows=is_windows,
                ax_create_application_fn=ax_create_application_fn,
            )

        def refresh_main_window(self):
            return label_refresh_main_window(
                self,
                is_windows=is_windows,
                ax_create_application_fn=ax_create_application_fn,
                get_attr_fn=get_attr_fn,
            )

        def get_window_frame(self):
            if is_windows:
                try:
                    return win32_window_info.get_window_rect(int(self.target_hwnd or 0))
                except Exception:
                    return None
            if not self.main_win:
                self.refresh_main_window()
            if not self.main_win:
                return None
            try:
                return self._get_element_frame(self.main_win)
            except Exception:
                return None

        def activate_color_page(self):
            return label_activate_color_page(
                self,
                target_texts={'Color', '??'},
                is_windows=is_windows,
                simulate_mouse_drag_fn=platform_mouse_input.simulate_mouse_drag,
                sleep_fn=sleep_fn,
                ax_perform_action_fn=ax_perform_action_fn,
                press_action=press_action,
                get_attr_fn=get_attr_fn,
                parse_ax_frame_fn=parse_ax_frame_value,
            )

        def find_first_text(self, target_text, max_depth=30):
            if not self.refresh_main_window():
                return None
            return scan_first_text(
                self.main_win,
                target_text,
                get_element_text_fn=self._get_element_text,
                get_element_children_fn=self._get_element_children,
                max_depth=max_depth,
            )

        def find_labels(self):
            if not self._layout_scan_call(self.refresh_main_window):
                self.labels = []
                return []

            results = self._layout_scan_call(
                scan_wheel_labels,
                self.main_win,
                get_element_text_fn=self._layout_scan_callback(self._get_element_text),
                get_element_frame_fn=self._layout_scan_callback(self._get_element_frame),
                get_element_children_fn=self._layout_scan_callback(self._get_element_children),
            )
            self.labels = results
            return results

        def _layout_scan_call(self, callback, *args, **kwargs):
            """Yield between discovery operations, never inside shared AX accessors."""
            check_layout_scan(self)
            result = callback(*args, **kwargs)
            check_layout_scan(self)
            return result

        def _layout_scan_callback(self, callback):
            # Normal/manual discovery keeps its original callbacks. Only a
            # scheduled scan installs the cooperative cancellation checkpoint.
            if getattr(self, '_layout_scan_checkpoint', None) is None:
                return callback
            return partial(self._layout_scan_call, callback)

        def get_diagnostic_texts(self, limit=12):
            if not self.refresh_main_window():
                return []
            return collect_diagnostic_texts(
                self.main_win,
                get_element_text_fn=self._get_element_text,
                get_element_children_fn=self._get_element_children,
                limit=limit,
            )

        def _get_element_text(self, element):
            return access_get_element_text(
                element,
                is_windows=is_windows,
                ax_text_attributes=ax_text_attributes,
                get_attr_fn=get_attr_fn,
            )

        def _get_element_frame(self, element):
            return access_get_element_frame(
                element,
                is_windows=is_windows,
                get_attr_fn=get_attr_fn,
                parse_ax_frame_fn=parse_ax_frame_value,
            )

        def _get_element_children(self, element):
            return access_get_element_children(
                element,
                is_windows=is_windows,
                get_attr_fn=get_attr_fn,
            )

        def _get_element_role(self, element):
            return access_get_element_role(
                element,
                is_windows=is_windows,
                get_attr_fn=get_attr_fn,
            )

        def _click_element(self, element):
            return access_click_element(
                element,
                is_windows=is_windows,
                ax_perform_action_fn=ax_perform_action_fn,
                press_action=press_action,
            )

        def find_numeric_inputs(self):
            if not self._layout_scan_call(self.refresh_main_window):
                return []

            return self._layout_scan_call(
                scan_numeric_inputs,
                self.main_win,
                is_windows=is_windows,
                get_element_role_fn=self._layout_scan_callback(self._get_element_role),
                get_element_text_fn=self._layout_scan_callback(self._get_element_text),
                get_element_frame_fn=self._layout_scan_callback(self._get_element_frame),
                get_element_children_fn=self._layout_scan_callback(self._get_element_children),
            )

        def find_vertical_sliders(self):
            if not self._layout_scan_call(self.refresh_main_window):
                return []

            return self._layout_scan_call(
                scan_vertical_slider_inputs,
                self.main_win,
                get_element_role_fn=self._layout_scan_callback(self._get_element_role),
                get_element_text_fn=self._layout_scan_callback(self._get_element_text),
                get_element_frame_fn=self._layout_scan_callback(self._get_element_frame),
                get_element_children_fn=self._layout_scan_callback(self._get_element_children),
            )

        def calculate_wheel_areas(self):
            numeric_inputs = self._layout_scan_call(self.find_numeric_inputs)
            vertical_sliders = self._layout_scan_call(self.find_vertical_sliders)
            window_frame = self._layout_scan_call(self.get_window_frame)
            pid = self.target_pid
            if is_mac and self.target_app is not None:
                pid = self.target_app.processIdentifier()
            geometry_key = layout_geometry_context(
                window_frame, pid, self.target_hwnd,
                self.labels, numeric_inputs, vertical_sliders,
            )
            can_confirm = bool(self._layout_scan_call(self.is_frontmost))
            scan = self._wheel_geometry_cache.begin_scan(
                geometry_key, allow_measure=can_confirm,
            )
            areas = self._layout_scan_call(
                calculate_wheel_target_areas,
                self.labels,
                numeric_inputs,
                is_windows=is_windows,
                vertical_sliders=vertical_sliders,
                detect_vertical_slider_tracks_fn=self._layout_scan_callback(
                    wheel_detection_adapter.detect_vertical_slider_tracks,
                ),
                detect_horizontal_slider_track_fn=self._layout_scan_callback(
                    wheel_detection_adapter.detect_horizontal_slider_track,
                ),
                detect_wheel_circle_fn=self._layout_scan_callback(
                    lambda area: scan.detect(
                        area, wheel_detection_adapter.detect_wheel_circle_in_area,
                    ),
                ),
                debug_slow_fn=debug_slow_fn,
            )
            # The outer _layout_scan_call performs its final cancellation check
            # before publishing any geometry from this complete scan.
            if self._wheel_geometry_cache.commit(scan) and debug_slow_fn:
                debug_slow_fn(
                    f"wheel geometry layout-lock measured={scan.measured} "
                    f"reused={scan.reused} valid_context={geometry_key is not None} "
                    f"can_confirm={can_confirm}"
                )
            return areas

    LabelFinder.__name__ = 'LabelFinder'
    return LabelFinder


__all__ = ['create_label_finder_class']
