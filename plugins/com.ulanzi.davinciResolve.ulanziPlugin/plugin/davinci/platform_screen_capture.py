"""Platform screen capture helpers for pixel-based DaVinci UI detection."""

import os
import subprocess
import tempfile
import time


def _normalize_capture_image_to_logical_size(image, logical_width, logical_height):
    """Return a 1x image when macOS captures a Retina region at backing scale."""
    logical_width = int(logical_width)
    logical_height = int(logical_height)
    if logical_width <= 0 or logical_height <= 0:
        return image, 1.0, 1.0

    captured_width = int(image.width())
    captured_height = int(image.height())
    if captured_width <= 0 or captured_height <= 0:
        return image, 1.0, 1.0

    scale_x = captured_width / logical_width
    scale_y = captured_height / logical_height
    if captured_width == logical_width and captured_height == logical_height:
        return image, 1.0, 1.0

    # A Retina capture is uniformly larger than the logical region. Avoid
    # stretching genuinely clipped or otherwise malformed screenshots.
    scale_tolerance = max(0.05, max(scale_x, scale_y) * 0.05)
    uniform_scale = abs(scale_x - scale_y) <= scale_tolerance
    plausible_backing_scale = 0.95 <= scale_x <= 4.0 and 0.95 <= scale_y <= 4.0
    if not uniform_scale or not plausible_backing_scale:
        return image, 1.0, 1.0

    normalized = image.scaled(logical_width, logical_height)
    if normalized is None or normalized.isNull():
        return image, 1.0, 1.0
    return normalized, scale_x, scale_y


class PlatformScreenCapture:
    def __init__(
        self,
        *,
        is_windows,
        win32_available,
        pyqt_available,
        user32=None,
        gdi32=None,
        ctypes_module=None,
        bitmap_info_cls=None,
        bitmap_info_header_cls=None,
        q_application_cls=None,
        q_image_cls=None,
        sys_argv=None,
        srccopy=0,
        captureblt=0,
        bi_rgb=0,
        dib_rgb_colors=0,
    ):
        self.is_windows = is_windows
        self.win32_available = win32_available
        self.pyqt_available = pyqt_available
        self.user32 = user32
        self.gdi32 = gdi32
        self.ctypes = ctypes_module
        self.bitmap_info_cls = bitmap_info_cls
        self.bitmap_info_header_cls = bitmap_info_header_cls
        self.q_application_cls = q_application_cls
        self.q_image_cls = q_image_cls
        self.sys_argv = sys_argv or []
        self.srccopy = srccopy
        self.captureblt = captureblt
        self.bi_rgb = bi_rgb
        self.dib_rgb_colors = dib_rgb_colors
        self.last_capture_scale = (1.0, 1.0)

    def capture_region(self, x, y, w, h):
        if self.is_windows and self.win32_available:
            return self.capture_region_windows(x, y, w, h)

        if not self.pyqt_available or not self.q_application_cls or not self.q_image_cls:
            return None, 0, 0, 0, 0

        x, y, w, h = int(x), int(y), int(w), int(h)

        fd, temp_path = tempfile.mkstemp(suffix='.png')
        os.close(fd)

        try:
            cmd = ['screencapture', '-x', '-R', f'{x},{y},{w},{h}', temp_path]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0 or not os.path.exists(temp_path):
                return None, 0, 0, 0, 0

            time.sleep(0.05)

            if not self.q_application_cls.instance():
                self.q_application_cls(self.sys_argv)

            image = self.q_image_cls(temp_path)
            os.remove(temp_path)

            if image.isNull():
                return None, 0, 0, 0, 0

            image, scale_x, scale_y = _normalize_capture_image_to_logical_size(
                image,
                w,
                h,
            )
            self.last_capture_scale = (scale_x, scale_y)
            image = image.convertToFormat(self.q_image_cls.Format_RGBA8888)
            width = image.width()
            height = image.height()
            bytes_per_row = image.bytesPerLine()
            bytes_per_pixel = 4

            ptr = image.bits()
            pixel_data = bytes(ptr.asstring(bytes_per_row * height))

            return pixel_data, width, height, bytes_per_row, bytes_per_pixel

        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return None, 0, 0, 0, 0

    def capture_region_windows(self, x, y, w, h):
        if not (
            self.win32_available
            and self.user32
            and self.gdi32
            and self.ctypes
            and self.bitmap_info_cls
            and self.bitmap_info_header_cls
        ):
            return None, 0, 0, 0, 0

        x, y, w, h = int(x), int(y), int(w), int(h)
        if w <= 0 or h <= 0:
            return None, 0, 0, 0, 0

        screen_dc = self.user32.GetDC(None)
        mem_dc = self.gdi32.CreateCompatibleDC(screen_dc)
        bitmap = self.gdi32.CreateCompatibleBitmap(screen_dc, w, h)
        old_bitmap = self.gdi32.SelectObject(mem_dc, bitmap)

        try:
            if not self.gdi32.BitBlt(
                mem_dc,
                0,
                0,
                w,
                h,
                screen_dc,
                x,
                y,
                self.srccopy | self.captureblt,
            ):
                return None, 0, 0, 0, 0

            bmi = self.bitmap_info_cls()
            bmi.bmiHeader.biSize = self.ctypes.sizeof(self.bitmap_info_header_cls)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = self.bi_rgb

            bgra = (self.ctypes.c_ubyte * (w * h * 4))()
            lines = self.gdi32.GetDIBits(
                mem_dc,
                bitmap,
                0,
                h,
                bgra,
                self.ctypes.byref(bmi),
                self.dib_rgb_colors,
            )
            if lines == 0:
                return None, 0, 0, 0, 0

            rgba = bytearray(w * h * 4)
            for offset in range(0, len(rgba), 4):
                rgba[offset] = bgra[offset + 2]
                rgba[offset + 1] = bgra[offset + 1]
                rgba[offset + 2] = bgra[offset]
                rgba[offset + 3] = bgra[offset + 3]

            return bytes(rgba), w, h, w * 4, 4
        finally:
            if old_bitmap:
                self.gdi32.SelectObject(mem_dc, old_bitmap)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            if mem_dc:
                self.gdi32.DeleteDC(mem_dc)
            if screen_dc:
                self.user32.ReleaseDC(None, screen_dc)
