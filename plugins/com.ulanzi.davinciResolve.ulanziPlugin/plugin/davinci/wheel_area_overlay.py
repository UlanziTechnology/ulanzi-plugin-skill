"""Wheel-area overlay widget factory."""

import time
from threading import current_thread

from .overlay_colors import _argb_from_hex, _colorref_from_hex
from .overlay_native_alpha_paint import (
    draw_native_alpha_corners,
    draw_native_alpha_wheel_state,
    redraw_native_alpha_dot,
    redraw_native_alpha_overlay,
)
from .overlay_native_paint import (
    draw_native_filled_ellipse,
    paint_native_overlay,
    redraw_native_overlay_window,
)
from .overlay_qt_paint import paint_qt_overlay
from .overlay_tk_paint import redraw_tk_overlay
from .overlay_windowing import (
    apply_tk_click_through,
    create_native_overlay_window,
    create_tk_overlay,
    initialize_overlay_backend,
    setup_qt_overlay_window,
)
from .overlay_window_visibility import (
    delete_native_overlay,
    delete_tk_overlay,
    hide_native_dot_window,
    hide_native_overlay,
    hide_tk_overlay,
    refresh_overlay_surface,
    show_native_overlay,
    show_tk_overlay,
    update_overlay_geometry,
)
from .wheel_visual_paint import wheel_state_for_paint


def create_wheel_area_overlay_class(
    *,
    widget_cls,
    sys_platform,
    force_win32_native,
    is_windows,
    win32_available,
    tkinter_available,
    win32_overlay_available,
    pyqt_available,
    tk_root_provider,
    tk_module,
    tk_error_cls,
    native_bindings,
    native_runtime,
    user32,
    gdi32,
    gdiplus,
    ctypes_module,
    rect_cls,
    qt_cls,
    c_void_p_cls,
    q_painter_cls,
    q_color_cls,
    q_pen_cls,
    q_svg_renderer_cls,
    q_byte_array_cls,
    q_rectf_cls,
    overlay_native_use_per_pixel_alpha,
    wheel_dot_radius,
    wheel_dot_svg_template,
    corner_length,
    corner_width,
    corner_inset,
    corner_active_color,
    corner_color,
    hwnd_topmost,
    sw_hide,
    swp_noactivate,
    swp_showwindow,
    get_window_long_fn,
    set_window_long_fn,
    gwl_exstyle,
    ws_ex_layered,
    ws_ex_transparent,
    ws_ex_topmost,
    ws_ex_toolwindow,
    ws_ex_noactivate,
    lwa_colorkey,
    swp_nomove,
    swp_nosize,
    ps_solid,
    gdip_unit_pixel,
):
    class WheelAreaOverlay(widget_cls):
        """Wheel-area overlay with backend-specific transparent drawing."""

        def __init__(self, area):
            super().__init__()
            self.area = area
            self.wheel_state = None
            self.wheel_dot_hidden = False
            self.hovered = False
            self._tk_window = None
            self._tk_canvas = None
            self._tk_visible = False
            self._tk_transparent_color_ref = 0x00030201
            self._native_hwnd = None
            self._native_visible = False
            self._native_dot_hwnd = None
            self._native_dot_visible = False
            self._native_transparent_color_ref = 0x00030201
            self.init_ui()

        def init_ui(self):
            return initialize_overlay_backend(
                force_win32_native=force_win32_native,
                is_windows=is_windows,
                win32_available=win32_available,
                tkinter_available=tkinter_available,
                win32_overlay_available=win32_overlay_available,
                pyqt_available=pyqt_available,
                init_native_fn=self._init_native_ui,
                native_ready_fn=lambda: bool(self._native_hwnd),
                init_tk_fn=self._init_tk_ui,
                setup_qt_fn=self._setup_qt_ui,
            )

        def _setup_qt_ui(self):
            return setup_qt_overlay_window(
                self,
                update_geometry_fn=self._update_geometry,
                sys_platform=sys_platform,
                qt_cls=qt_cls,
                c_void_p_cls=c_void_p_cls,
            )

        def _init_tk_ui(self):
            self._tk_window, self._tk_canvas = create_tk_overlay(
                tk_root_provider.get(tkinter_available=tkinter_available, tk_module=tk_module),
                tk_module=tk_module,
                tk_error_cls=tk_error_cls,
                transparent_color='#010203',
            )
            if not self._tk_window:
                return

            self._update_geometry()
            self._apply_click_through()
            self._redraw_tk()

        def _init_native_ui(self):
            hwnd, dot_hwnd, creation_failed = create_native_overlay_window(
                **native_bindings.native_create_kwargs(
                    self,
                    self._overlay_geometry(),
                    self._native_transparent_color_ref,
                ),
            )
            if creation_failed:
                print("Win32 overlay window creation failed")
            if not hwnd:
                return

            self._native_hwnd = hwnd
            self._native_dot_hwnd = dot_hwnd

        def _overlay_geometry(self):
            return (
                int(self.area.get('overlay_x', self.area['x'])),
                int(self.area.get('overlay_y', self.area['y'])),
                max(1, int(self.area.get('overlay_w', self.area['w']))),
                max(1, int(self.area.get('overlay_h', self.area['h']))),
            )

        def _update_geometry(self):
            return update_overlay_geometry(
                self._overlay_geometry(),
                tk_window=self._tk_window,
                tk_canvas=self._tk_canvas,
                native_hwnd=self._native_hwnd,
                native_visible=self._native_visible,
                redraw_tk_fn=self._redraw_tk,
                redraw_native_fn=self._redraw_native,
                set_geometry_fn=self.setGeometry,
                user32=user32,
                hwnd_topmost=hwnd_topmost,
                swp_noactivate=swp_noactivate,
                swp_showwindow=swp_showwindow,
            )

        def update_area(self, area):
            self.area = area
            self._update_geometry()
            self.update()

        def update_wheel_state(self, state):
            self.wheel_state = state
            return refresh_overlay_surface(
                tk_canvas=self._tk_canvas,
                native_hwnd=self._native_hwnd,
                redraw_tk_fn=self._redraw_tk,
                redraw_native_fn=self._redraw_native,
                update_qt_fn=self.update,
            )

        def set_wheel_dot_hidden(self, hidden):
            hidden = bool(hidden)
            if self.wheel_dot_hidden == hidden:
                return

            self.wheel_dot_hidden = hidden
            if self._native_dot_hwnd:
                if hidden:
                    hide_native_dot_window(
                        self._native_dot_hwnd,
                        user32=user32,
                        sw_hide=sw_hide,
                    )
                    self._native_dot_visible = False
                else:
                    self._redraw_native_dot()
                return
            return refresh_overlay_surface(
                tk_canvas=self._tk_canvas,
                native_hwnd=self._native_hwnd,
                redraw_tk_fn=self._redraw_tk,
                redraw_native_fn=self._redraw_native,
                update_qt_fn=self.update,
            )

        def hide_for_manual_drag_immediate(self):
            if self._native_dot_hwnd:
                self.wheel_dot_hidden = True
                hide_native_dot_window(
                    self._native_dot_hwnd,
                    user32=user32,
                    sw_hide=sw_hide,
                )
                self._native_dot_visible = False
                return True
            self.set_wheel_dot_hidden(True)
            return True

        def _wheel_state_for_paint(self, allow_dot_outside=False):
            return wheel_state_for_paint(
                self.area,
                self.wheel_state,
                self._overlay_geometry(),
                wheel_dot_hidden=self.wheel_dot_hidden,
                allow_dot_outside=allow_dot_outside,
            )

        def set_hovered(self, hovered):
            if self.hovered != hovered:
                self.hovered = hovered
                return refresh_overlay_surface(
                    tk_canvas=self._tk_canvas,
                    native_hwnd=self._native_hwnd,
                    redraw_tk_fn=self._redraw_tk,
                    redraw_native_fn=self._redraw_native,
                    update_qt_fn=self.update,
                )

        def _apply_click_through(self):
            return apply_tk_click_through(
                self._tk_window,
                is_windows=is_windows,
                win32_available=win32_available,
                get_window_long_fn=get_window_long_fn,
                set_window_long_fn=set_window_long_fn,
                user32=user32,
                transparent_color_ref=self._tk_transparent_color_ref,
                gwl_exstyle=gwl_exstyle,
                ws_ex_layered=ws_ex_layered,
                ws_ex_transparent=ws_ex_transparent,
                ws_ex_topmost=ws_ex_topmost,
                ws_ex_toolwindow=ws_ex_toolwindow,
                ws_ex_noactivate=ws_ex_noactivate,
                lwa_colorkey=lwa_colorkey,
                hwnd_topmost=hwnd_topmost,
                swp_nomove=swp_nomove,
                swp_nosize=swp_nosize,
                swp_noactivate=swp_noactivate,
            )

        def _redraw_tk(self):
            return redraw_tk_overlay(
                self._tk_canvas,
                self._overlay_geometry(),
                self._wheel_state_for_paint(),
                hovered=self.hovered,
                wheel_dot_radius=wheel_dot_radius,
                corner_length=corner_length,
                corner_width=corner_width,
                corner_inset=corner_inset,
                active_color=corner_active_color,
                inactive_color=corner_color,
            )

        def _native_draw_filled_ellipse(self, hdc, cx, cy, radius, fill_color, outline_color, outline_width=1):
            return draw_native_filled_ellipse(
                hdc,
                cx,
                cy,
                radius,
                fill_color,
                outline_color,
                outline_width=outline_width,
                gdi32=gdi32,
                colorref_from_hex_fn=_colorref_from_hex,
                ps_solid=ps_solid,
            )

        def _draw_native_wheel_state(self, hdc):
            wheel = self._wheel_state_for_paint()
            if not wheel:
                return

            self._native_draw_filled_ellipse(
                hdc,
                wheel['px'],
                wheel['py'],
                wheel_dot_radius,
                wheel['color'],
                wheel['color'],
                1,
            )

        def _paint_native(self, hdc):
            return paint_native_overlay(
                hdc,
                self._overlay_geometry(),
                draw_wheel_fn=self._draw_native_wheel_state,
                has_dot_window=bool(self._native_dot_hwnd),
                hovered=self.hovered,
                transparent_color_ref=self._native_transparent_color_ref,
                gdi32=gdi32,
                user32=user32,
                ctypes_module=ctypes_module,
                rect_cls=rect_cls,
                corner_length=corner_length,
                corner_width=corner_width,
                corner_inset=corner_inset,
                active_color=corner_active_color,
                inactive_color=corner_color,
                colorref_from_hex_fn=_colorref_from_hex,
                ps_solid=ps_solid,
            )

        def _draw_native_alpha_wheel_state(self, graphics):
            return draw_native_alpha_wheel_state(
                graphics,
                self._wheel_state_for_paint(),
                gdiplus=gdiplus,
                ctypes_module=ctypes_module,
                argb_from_hex_fn=_argb_from_hex,
                dot_radius=wheel_dot_radius,
            )

        def _draw_native_alpha_corners(self, graphics, w, h):
            return draw_native_alpha_corners(
                graphics,
                width=w,
                height=h,
                hovered=self.hovered,
                gdiplus=gdiplus,
                ctypes_module=ctypes_module,
                argb_from_hex_fn=_argb_from_hex,
                corner_length=corner_length,
                corner_width=corner_width,
                corner_inset=corner_inset,
                active_color=corner_active_color,
                inactive_color=corner_color,
                gdip_unit_pixel=gdip_unit_pixel,
            )

        def _redraw_native_alpha(self):
            def draw_content(graphics, w, h):
                self._draw_native_alpha_corners(graphics, w, h)

            return redraw_native_alpha_overlay(
                self._native_hwnd,
                self._overlay_geometry(),
                draw_content_fn=draw_content,
                **native_bindings.alpha_base_kwargs(),
            )

        def _redraw_native_dot(self):
            updated, visible = redraw_native_alpha_dot(
                self._native_dot_hwnd,
                self._wheel_state_for_paint(allow_dot_outside=True),
                self._overlay_geometry(),
                dot_hidden=self.wheel_dot_hidden,
                native_visible=self._native_visible,
                **native_bindings.alpha_dot_kwargs(),
            )
            self._native_dot_visible = visible
            return updated

        def _redraw_native(self):
            return redraw_native_overlay_window(
                self._native_hwnd,
                native_use_per_pixel_alpha=overlay_native_use_per_pixel_alpha,
                redraw_native_alpha_fn=self._redraw_native_alpha,
                redraw_native_dot_fn=self._redraw_native_dot,
                paint_native_fn=self._paint_native,
                user32=user32,
                transparent_color_ref=self._native_transparent_color_ref,
                lwa_colorkey=lwa_colorkey,
            )

        def show(self):
            if self._tk_window:
                self._tk_visible = show_tk_overlay(
                    self._tk_window,
                    update_geometry_fn=self._update_geometry,
                    apply_click_through_fn=self._apply_click_through,
                    **native_bindings.window_show_kwargs(),
                )
                return
            if self._native_hwnd:
                self._native_visible = True
                visible = show_native_overlay(
                    self._native_hwnd,
                    update_geometry_fn=self._update_geometry,
                    redraw_native_fn=self._redraw_native,
                    **native_bindings.window_show_kwargs(),
                )
                self._native_visible = visible
                return
            if pyqt_available:
                super().show()
                if sys_platform == 'darwin':
                    ns_window = getattr(self, '_mac_ns_window', None)
                    if ns_window:
                        ns_window.orderFrontRegardless()

        def hide(self):
            if self._tk_window:
                self._tk_visible = hide_tk_overlay(
                    self._tk_window,
                    **native_bindings.window_hide_kwargs(),
                )
                return
            if self._native_hwnd:
                self._native_visible, self._native_dot_visible = hide_native_overlay(
                    self._native_hwnd,
                    self._native_dot_hwnd,
                    **native_bindings.window_hide_kwargs(),
                )
                return
            if pyqt_available:
                super().hide()

        def isVisible(self):
            if self._tk_window:
                return self._tk_visible
            if self._native_hwnd:
                return self._native_visible
            if pyqt_available:
                return super().isVisible()
            return False

        def deleteLater(self):
            if self._tk_window:
                self._tk_window, self._tk_canvas = delete_tk_overlay(
                    self._tk_window,
                    self._tk_canvas,
                    tk_error_cls=tk_error_cls,
                )
                return
            if self._native_hwnd:
                (
                    self._native_hwnd,
                    self._native_dot_hwnd,
                    self._native_visible,
                    self._native_dot_visible,
                ) = delete_native_overlay(
                    self._native_hwnd,
                    self._native_dot_hwnd,
                    instances=native_runtime.instances,
                    **native_bindings.window_hide_kwargs(),
                )
                return
            if pyqt_available:
                super().deleteLater()

        def paintEvent(self, event):
            started_at = time.monotonic()
            wheel = self._wheel_state_for_paint()
            trace_state = dict(getattr(self, "_smooth_cadence_state", {}) or {})
            result = paint_qt_overlay(
                self,
                wheel,
                hovered=self.hovered,
                pyqt_available=pyqt_available,
                q_painter_cls=q_painter_cls,
                q_color_cls=q_color_cls,
                q_pen_cls=q_pen_cls,
                q_svg_renderer_cls=q_svg_renderer_cls,
                q_byte_array_cls=q_byte_array_cls,
                q_rectf_cls=q_rectf_cls,
                qt_cls=qt_cls,
                wheel_dot_radius=wheel_dot_radius,
                dot_svg_template=wheel_dot_svg_template,
                corner_length=corner_length,
                corner_width=corner_width,
                corner_inset=corner_inset,
                active_color=corner_active_color,
                inactive_color=corner_color,
            )

            trace = getattr(self, "_smooth_cadence_trace", None)
            if callable(trace) and trace_state and wheel is not None:
                try:
                    trace("cadence_overlay_paint", **trace_state,
                          paintStartedAt=started_at,
                          paintFinishedAt=time.monotonic(),
                          paintedAngle=wheel.get("angle"),
                          threadName=current_thread().name)
                except Exception:
                    pass
            return result

    WheelAreaOverlay.__name__ = 'WheelAreaOverlay'
    return WheelAreaOverlay


__all__ = ['create_wheel_area_overlay_class']
