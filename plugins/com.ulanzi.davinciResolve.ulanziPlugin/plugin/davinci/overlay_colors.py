"""Color helpers used by overlays and wheel state."""

import colorsys
import math


def _colorref_from_hex(hex_color):
    color = hex_color.lstrip('#')
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return r | (g << 8) | (b << 16)


def _argb_from_hex(hex_color, alpha=255):
    color = hex_color.lstrip('#')
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return ((alpha & 0xff) << 24) | (r << 16) | (g << 8) | b


def _wheel_hue_hex(angle, saturation=0.98, value=1.0):
    hue = ((240.0 - math.degrees(angle)) % 360.0) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
    return f'#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}'


__all__ = [
    '_argb_from_hex',
    '_colorref_from_hex',
    '_wheel_hue_hex',
]
