"""Win32 overlay dependency bundle helpers."""


class OverlayNativeBindings:
    """Build keyword-argument bundles for native overlay helpers."""

    def __init__(self, **deps):
        self._deps = deps

    def alpha_base_kwargs(self):
        deps = self._deps
        return {
            'gdiplus_ready': deps['ensure_gdiplus_fn'](),
            'gdiplus': deps['gdiplus'],
            'gdi32': deps['gdi32'],
            'user32': deps['user32'],
            'ctypes_module': deps['ctypes_module'],
            'bitmap_info_cls': deps['bitmap_info_cls'],
            'bitmap_info_header_cls': deps['bitmap_info_header_cls'],
            'point_cls': deps['point_cls'],
            'size_cls': deps['size_cls'],
            'blend_function_cls': deps['blend_function_cls'],
            'bi_rgb': deps['bi_rgb'],
            'dib_rgb_colors': deps['dib_rgb_colors'],
            'smoothing_mode': deps['smoothing_mode'],
            'pixel_offset_mode': deps['pixel_offset_mode'],
            'ac_src_over': deps['ac_src_over'],
            'ac_src_alpha': deps['ac_src_alpha'],
            'ulw_alpha': deps['ulw_alpha'],
        }

    def alpha_dot_kwargs(self):
        deps = self._deps
        kwargs = self.alpha_base_kwargs()
        kwargs.update({
            'argb_from_hex_fn': deps['argb_from_hex_fn'],
            'dot_radius': deps['dot_radius'],
            'sw_hide': deps['sw_hide'],
            'sw_shownoactivate': deps['sw_shownoactivate'],
            'hwnd_topmost': deps['hwnd_topmost'],
            'swp_noactivate': deps['swp_noactivate'],
            'swp_showwindow': deps['swp_showwindow'],
        })
        return kwargs

    def window_show_kwargs(self):
        deps = self._deps
        return {
            'user32': deps['user32'],
            'hwnd_topmost': deps['hwnd_topmost'],
            'sw_shownoactivate': deps['sw_shownoactivate'],
            'swp_nomove': deps['swp_nomove'],
            'swp_nosize': deps['swp_nosize'],
            'swp_noactivate': deps['swp_noactivate'],
            'swp_showwindow': deps['swp_showwindow'],
        }

    def window_hide_kwargs(self):
        deps = self._deps
        return {
            'user32': deps['user32'],
            'sw_hide': deps['sw_hide'],
        }

    def native_create_kwargs(self, owner, overlay_geometry, transparent_color_ref):
        deps = self._deps
        return {
            'overlay_geometry': overlay_geometry,
            'owner': owner,
            'instances': deps['instances'],
            'ensure_class_fn': deps['ensure_class_fn'],
            'native_use_per_pixel_alpha': deps['native_use_per_pixel_alpha'],
            'dot_radius': deps['dot_radius'],
            'transparent_color_ref': transparent_color_ref,
            'user32': deps['user32'],
            'kernel32': deps['kernel32'],
            'class_name': deps['class_name'],
            'ws_ex_layered': deps['ws_ex_layered'],
            'ws_ex_transparent': deps['ws_ex_transparent'],
            'ws_ex_topmost': deps['ws_ex_topmost'],
            'ws_ex_toolwindow': deps['ws_ex_toolwindow'],
            'ws_ex_noactivate': deps['ws_ex_noactivate'],
            'ws_popup': deps['ws_popup'],
            'lwa_colorkey': deps['lwa_colorkey'],
            'sw_hide': deps['sw_hide'],
        }


__all__ = ['OverlayNativeBindings']
